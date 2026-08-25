"""Encrypted local secret vault for AI Fleet OS."""

import base64
import ctypes
import json
import os
from pathlib import Path
from typing import Dict, Optional

VAULT_DIR = Path(os.environ.get("AI_FLEET_DATA_DIR", str(Path.home() / ".ai_fleet")))
VAULT_FILE = VAULT_DIR / "secrets.json"
FALLBACK_KEY_FILE = VAULT_DIR / ".vault.key"

PROVIDER_ENV_MAPPINGS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GEMINI_API_KEY",
    "alibaba": "DASHSCOPE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama_host": "OLLAMA_HOST",
    "bedrock": "AWS_BEARER_TOKEN_BEDROCK",
}


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _windows_dpapi(data: bytes, decrypt: bool = False) -> bytes:
    """Encrypt or decrypt bytes for the current Windows user with DPAPI."""
    buffer = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    if not function(ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _fallback_cipher():
    """Use a per-user local Fernet key where Windows DPAPI is unavailable."""
    from cryptography.fernet import Fernet

    if not FALLBACK_KEY_FILE.exists():
        FALLBACK_KEY_FILE.write_bytes(Fernet.generate_key())
        try:
            FALLBACK_KEY_FILE.chmod(0o600)
        except OSError:
            pass
    return Fernet(FALLBACK_KEY_FILE.read_bytes())


def _encrypt_payload(data: bytes) -> tuple[str, bytes]:
    if os.name == "nt":
        return "windows-dpapi", _windows_dpapi(data)
    return "fernet", _fallback_cipher().encrypt(data)


def _decrypt_payload(scheme: str, data: bytes) -> bytes:
    if scheme == "windows-dpapi" and os.name == "nt":
        return _windows_dpapi(data, decrypt=True)
    if scheme == "fernet":
        return _fallback_cipher().decrypt(data)
    raise ValueError(f"Unsupported vault encryption scheme: {scheme}")


class SecretVault:
    """Manages local API keys and secrets securely."""

    def __init__(self):
        VAULT_DIR.mkdir(parents=True, exist_ok=True)
        self._secrets: Dict[str, str] = {}
        self._load()

    def _load(self):
        if VAULT_FILE.exists():
            try:
                with open(VAULT_FILE, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                if stored.get("version") == 2 and stored.get("payload"):
                    encrypted = base64.b64decode(stored["payload"])
                    decrypted = _decrypt_payload(stored["scheme"], encrypted)
                    self._secrets = json.loads(decrypted.decode("utf-8"))
                else:
                    # One-time migration from the legacy plaintext dictionary.
                    self._secrets = stored
                    self._save()
            except Exception:
                self._secrets = {}
        else:
            self._secrets = {}

    def _save(self):
        try:
            scheme, encrypted = _encrypt_payload(json.dumps(self._secrets).encode("utf-8"))
            stored = {
                "version": 2,
                "scheme": scheme,
                "payload": base64.b64encode(encrypted).decode("ascii"),
            }
            with open(VAULT_FILE, "w", encoding="utf-8") as f:
                json.dump(stored, f, indent=2)
        except Exception as e:
            raise RuntimeError(f"Could not save the encrypted secret vault: {e}") from e

    def get_key(self, provider: str) -> Optional[str]:
        """Get API key from vault or fallback to environment variable."""
        # 1. Vault
        if provider in self._secrets and self._secrets[provider]:
            return self._secrets[provider]
        
        # 2. Environment variable
        env_var = PROVIDER_ENV_MAPPINGS.get(provider.lower())
        if env_var and env_var in os.environ:
            return os.environ[env_var]
        
        return None

    def set_key(self, provider: str, key_value: str):
        """Set and save an API key."""
        self._secrets[provider.lower()] = key_value.strip()
        self._save()

    def delete_key(self, provider: str):
        """Remove a key."""
        if provider.lower() in self._secrets:
            del self._secrets[provider.lower()]
            self._save()

    def has_key(self, key: str) -> bool:
        return bool(self._secrets.get(key.lower()))

    def redaction_values(self) -> list[str]:
        return [value for value in self._secrets.values() if value and len(value) >= 6]

    def list_configured_providers(self) -> Dict[str, Dict[str, any]]:
        """Return provider configuration status with masked keys."""
        status = {}
        for provider, env_var in PROVIDER_ENV_MAPPINGS.items():
            key = self.get_key(provider)
            is_configured = bool(key and len(key) > 4)
            masked = f"{key[:4]}...{key[-4:]}" if is_configured and len(key) > 8 else ("Configured" if is_configured else "Not Set")
            status[provider] = {
                "provider": provider,
                "is_configured": is_configured,
                "source": "vault" if provider in self._secrets else ("env" if env_var in os.environ else "none"),
                "masked_key": masked,
                "env_variable": env_var,
            }
        return status


secret_vault = SecretVault()
