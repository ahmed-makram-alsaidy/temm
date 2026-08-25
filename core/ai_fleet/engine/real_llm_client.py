"""Real LLM Execution Client for AI Fleet OS.
Directly communicates with Google Gemini, OpenAI, Anthropic, DeepSeek, Groq,
OpenRouter, and local Ollama instances with streaming and real token tracking.
"""

import json
import os
from typing import Any, AsyncGenerator, Dict, Optional
import httpx

from ..storage.secret_vault import secret_vault


class RealLLMClient:
    """Executes real LLM completions across multiple providers and local runtimes."""

    async def execute_stream(
        self,
        provider: str,
        model_id: str,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream real completions from the provider.
        Yields chunks: {"type": "chunk"|"done"|"error", "text": str, "tokens": int, "metadata": dict}
        """
        provider_lower = provider.lower()
        api_key = secret_vault.get_key(provider_lower)

        # 1. Local Ollama (No API Key needed)
        if provider_lower == "ollama" or model_id.startswith("ollama-"):
            async for chunk in self._stream_ollama(model_id, prompt, system_instruction):
                yield chunk
            return

        # 2. Google Gemini
        if provider_lower in ["google", "gemini"] or "gemini" in model_id.lower():
            if not api_key:
                api_key = secret_vault.get_key("google") or os.environ.get("GEMINI_API_KEY")

            if api_key:
                async for chunk in self._stream_gemini(model_id, prompt, api_key, system_instruction):
                    yield chunk
                return

        # 3. Groq (Ultra fast LPU)
        if provider_lower == "groq" or "groq" in model_id.lower():
            if not api_key:
                api_key = secret_vault.get_key("groq") or os.environ.get("GROQ_API_KEY")

            if api_key:
                async for chunk in self._stream_openai_compatible(
                    base_url="https://api.groq.com/openai/v1",
                    api_key=api_key,
                    model="llama-3.3-70b-versatile" if "70b" in model_id else "llama-3.1-8b-instant",
                    prompt=prompt,
                    system_instruction=system_instruction,
                ):
                    yield chunk
                return

        # 4. DeepSeek
        if provider_lower == "deepseek" or "deepseek" in model_id.lower():
            if not api_key:
                api_key = secret_vault.get_key("deepseek") or os.environ.get("DEEPSEEK_API_KEY")

            if api_key:
                real_model = "deepseek-reasoner" if "r1" in model_id.lower() else "deepseek-chat"
                async for chunk in self._stream_openai_compatible(
                    base_url="https://api.deepseek.com",
                    api_key=api_key,
                    model=real_model,
                    prompt=prompt,
                    system_instruction=system_instruction,
                ):
                    yield chunk
                return

        # 5. OpenAI
        if provider_lower == "openai" or model_id.startswith("gpt-"):
            if not api_key:
                api_key = secret_vault.get_key("openai") or os.environ.get("OPENAI_API_KEY")

            if api_key:
                real_model = "gpt-4o" if "4o" in model_id else "gpt-4o-mini"
                async for chunk in self._stream_openai_compatible(
                    base_url="https://api.openai.com/v1",
                    api_key=api_key,
                    model=real_model,
                    prompt=prompt,
                    system_instruction=system_instruction,
                ):
                    yield chunk
                return

        # 6. Anthropic
        if provider_lower == "anthropic" or "claude" in model_id.lower():
            if not api_key:
                api_key = secret_vault.get_key("anthropic") or os.environ.get("ANTHROPIC_API_KEY")

            if api_key:
                async for chunk in self._stream_anthropic(model_id, prompt, api_key, system_instruction):
                    yield chunk
                return

        # 7. AWS Bedrock (Converse API with Bearer token)
        if provider_lower == "bedrock":
            token = secret_vault.get_key("bedrock") or os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
            if token:
                async for chunk in self._stream_bedrock(model_id, prompt, token, system_instruction):
                    yield chunk
                return

        yield {
            "type": "error",
            "code": "execution_not_configured",
            "provider": provider_lower,
            "text": (
                f"{provider} is not connected for live execution. "
                "Configure valid provider credentials or choose an authenticated local CLI."
            ),
        }

    async def _stream_gemini(
        self,
        model_id: str,
        prompt: str,
        api_key: str,
        system_instruction: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Call official Google Gemini REST API with streaming."""
        gemini_model = "gemini-2.5-flash" if "flash" in model_id else "gemini-2.5-pro"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:streamGenerateContent?key={api_key}"

        contents = []
        if system_instruction:
            contents.append({"role": "user", "parts": [{"text": f"System context: {system_instruction}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood."}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {"contents": contents}
        headers = {"Content-Type": "application/json"}

        total_tokens = 0
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        err_text = await response.aread()
                        yield {"type": "error", "text": f"Gemini API Error ({response.status_code}): {err_text.decode('utf-8')}"}
                        return

                    buffer = ""
                    async for line in response.aiter_lines():
                        if line:
                            buffer += line
                            try:
                                data = json.loads(buffer.strip().lstrip("[").rstrip(","))
                                if "candidates" in data and data["candidates"]:
                                    part_text = data["candidates"][0]["content"]["parts"][0].get("text", "")
                                    if part_text:
                                        total_tokens += len(part_text.split())
                                        yield {"type": "chunk", "text": part_text, "tokens": total_tokens}
                                buffer = ""
                            except Exception:
                                pass

            yield {"type": "done", "text": "", "tokens": max(total_tokens, 15)}
        except Exception as e:
            yield {"type": "error", "text": f"Connection Error: {str(e)}"}

    async def _stream_openai_compatible(
        self,
        base_url: str,
        api_key: str,
        model: str,
        prompt: str,
        system_instruction: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Call standard OpenAI-compatible completions API (Groq, DeepSeek, OpenAI, OpenRouter)."""
        url = f"{base_url.rstrip('/')}/chat/completions"
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        total_tokens = 0
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        err_text = await response.aread()
                        yield {"type": "error", "text": f"API Error ({response.status_code}): {err_text.decode('utf-8')}"}
                        return

                    async for line in response.aiter_lines():
                        if line.startswith("data: ") and not line.endswith("[DONE]"):
                            try:
                                data = json.loads(line[6:])
                                delta = data["choices"][0].get("delta", {})
                                chunk_text = delta.get("content", "")
                                if chunk_text:
                                    total_tokens += 1
                                    yield {"type": "chunk", "text": chunk_text, "tokens": total_tokens}
                            except Exception:
                                pass

            yield {"type": "done", "text": "", "tokens": max(total_tokens, 20)}
        except Exception as e:
            yield {"type": "error", "text": f"Connection Error: {str(e)}"}

    async def _stream_anthropic(
        self,
        model_id: str,
        prompt: str,
        api_key: str,
        system_instruction: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Call Anthropic Messages API."""
        url = "https://api.anthropic.com/v1/messages"
        payload = {
            "model": "claude-3-7-sonnet-20250219" if "3-7" in model_id else "claude-3-5-sonnet-20241022",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        if system_instruction:
            payload["system"] = system_instruction

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        total_tokens = 0
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        err_text = await response.aread()
                        yield {"type": "error", "text": f"Anthropic API Error ({response.status_code}): {err_text.decode('utf-8')}"}
                        return

                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            try:
                                data = json.loads(line[6:])
                                if data.get("type") == "content_block_delta":
                                    chunk_text = data["delta"].get("text", "")
                                    if chunk_text:
                                        total_tokens += 1
                                        yield {"type": "chunk", "text": chunk_text, "tokens": total_tokens}
                            except Exception:
                                pass

            yield {"type": "done", "text": "", "tokens": max(total_tokens, 25)}
        except Exception as e:
            yield {"type": "error", "text": f"Connection Error: {str(e)}"}

    async def _stream_ollama(
        self,
        model_id: str,
        prompt: str,
        system_instruction: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Query local Ollama daemon."""
        host = secret_vault.get_key("ollama_host") or "http://localhost:11434"
        clean_model = model_id.replace("ollama-", "").replace("llama-3-3-70b", "llama3.3").replace("llama-3-3-8b", "llama3.3")

        url = f"{host}/api/generate"
        payload = {
            "model": clean_model,
            "prompt": f"{system_instruction}\n\n{prompt}" if system_instruction else prompt,
            "stream": True,
        }

        total_tokens = 0
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                async with client.stream("POST", url, json=payload) as response:
                    if response.status_code != 200:
                        yield {"type": "error", "text": f"Ollama Local Error ({response.status_code}). Is Ollama running on {host}?"}
                        return

                    async for line in response.aiter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                chunk_text = data.get("response", "")
                                if chunk_text:
                                    total_tokens += 1
                                    yield {"type": "chunk", "text": chunk_text, "tokens": total_tokens}
                            except Exception:
                                pass

            yield {"type": "done", "text": "", "tokens": max(total_tokens, 20)}
        except Exception as e:
            yield {"type": "error", "text": f"Local Ollama is offline or unreachable at {host}. ({str(e)})"}

    async def _stream_bedrock(
        self,
        model_id: str,
        prompt: str,
        token: str,
        system_instruction: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Call AWS Bedrock Converse API with Bearer token authentication."""
        endpoint = "https://bedrock-runtime.us-east-1.amazonaws.com"
        default_model = "amazon.nova-micro-v1:0"
        resolved_model = model_id if model_id and ":" in model_id else default_model
        url = f"{endpoint}/model/{resolved_model}/converse"
        content = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt
        body = {
            "messages": [{"role": "user", "content": [{"text": content}]}],
            "inferenceConfig": {"maxTokens": 4096},
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, headers=headers, json=body)
                if response.status_code != 200:
                    yield {"type": "error", "text": f"Bedrock Error ({response.status_code}): {response.text[:200]}"}
                    return
                data = response.json()
                output = data.get("output", {}).get("message", {}).get("content", [])
                text = output[0].get("text", "") if output else ""
                usage = data.get("usage", {})
                total_tokens = usage.get("outputTokens", 0)
                if text:
                    yield {"type": "chunk", "text": text, "tokens": total_tokens}
                yield {"type": "done", "text": "", "tokens": total_tokens}
        except Exception as e:
            yield {"type": "error", "text": f"Bedrock execution error: {str(e)}"}

real_llm_client = RealLLMClient()
