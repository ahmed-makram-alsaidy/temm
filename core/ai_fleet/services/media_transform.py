import hashlib
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ..errors import DomainError
from ..filesystem import PathPolicyError, path_policy
from ..storage.models import AssetRecord, AssetTransformJobRecord, WorkspaceRecord


IMAGE_FORMATS = {"png": ("png", "image/png"), "jpg": ("mjpeg", "image/jpeg"), "webp": ("libwebp", "image/webp")}
AUDIO_FORMATS = {"wav": ("pcm_s16le", "audio/wav"), "mp3": ("libmp3lame", "audio/mpeg"), "opus": ("libopus", "audio/ogg")}


class MediaTransformService:
    def __init__(self, manager, ffmpeg: str | None = None, ffprobe: str | None = None):
        self.manager = manager
        self.ffmpeg = ffmpeg or shutil.which("ffmpeg")
        self.ffprobe = ffprobe or shutil.which("ffprobe")

    def capability(self) -> dict[str, Any]:
        return {"available": bool(self.ffmpeg and self.ffprobe), "ffmpeg": self.ffmpeg, "ffprobe": self.ffprobe, "image_formats": sorted(IMAGE_FORMATS), "audio_formats": sorted(AUDIO_FORMATS), "features": ["resize", "crop", "thumbnail", "image_format", "audio_convert", "waveform", "timeout", "cancellation"] if self.ffmpeg and self.ffprobe else []}

    async def image(self, session, asset_id: str, output_path: str, parameters: dict[str, Any], timeout_seconds: float = 120, execution_id: str | None = None):
        output_format = str(parameters.get("format") or "png").lower()
        if output_format not in IMAGE_FORMATS:
            raise DomainError("validation_failed", message="Image output format is unsupported.")
        width = self._dimension(parameters.get("width"), "width")
        height = self._dimension(parameters.get("height"), "height")
        fit = str(parameters.get("fit") or "exact")
        quality = int(parameters.get("quality") or 85)
        if fit not in {"exact", "contain", "cover"} or not 1 <= quality <= 100:
            raise DomainError("validation_failed", message="Image fit or quality is invalid.")
        if fit in {"contain", "cover"} and not (width and height):
            raise DomainError("validation_failed", message="Contain and cover require width and height.")
        crop = parameters.get("crop")
        filters = []
        if crop is not None:
            if not isinstance(crop, dict):
                raise DomainError("validation_failed", message="Image crop is invalid.")
            values = [self._nonnegative(crop.get(key), key) for key in ("width", "height", "x", "y")]
            if not values[0] or not values[1]:
                raise DomainError("validation_failed", message="Image crop dimensions are required.")
            filters.append(f"crop={values[0]}:{values[1]}:{values[2]}:{values[3]}")
        if width or height:
            if fit == "contain":
                filters.extend([f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos", f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={'black' if output_format == 'jpg' else 'black@0.0'}"])
            elif fit == "cover":
                filters.extend([f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos", f"crop={width}:{height}"])
            else:
                filters.append(f"scale={width or -2}:{height or -2}:flags=lanczos")
        if not filters and output_format == Path(output_path).suffix.lower().lstrip("."):
            raise DomainError("validation_failed", message="Image transform must change dimensions, crop, or format.")
        if Path(output_path).suffix.lower() != f".{output_format}":
            raise DomainError("validation_failed", message="Image destination extension must match output format.")
        codec, mime = IMAGE_FORMATS[output_format]
        normalized = {"kind": "image", "format": output_format, "width": width, "height": height, "fit": fit, "quality": quality, "crop": crop or None}
        quality_args = ["-q:v", str(max(2, round((101 - quality) * 0.31)))] if output_format == "jpg" else ["-quality", str(quality)] if output_format == "webp" else ["-compression_level", str(round((100 - quality) * 0.09))]
        args = ["-map_metadata", "-1", "-frames:v", "1", "-c:v", codec, *quality_args]
        if filters:
            args = ["-vf", ",".join(filters), *args]
        return await self._execute(session, asset_id, output_path, normalized, args, "raster", mime, timeout_seconds, execution_id)

    async def audio(self, session, asset_id: str, output_path: str, parameters: dict[str, Any], timeout_seconds: float = 120, execution_id: str | None = None):
        output_format = str(parameters.get("format") or "wav").lower()
        if output_format not in AUDIO_FORMATS:
            raise DomainError("validation_failed", message="Audio output format is unsupported.")
        sample_rate = int(parameters.get("sample_rate") or 44100)
        channels = int(parameters.get("channels") or 2)
        if sample_rate not in {8000, 16000, 22050, 24000, 44100, 48000} or channels not in {1, 2}:
            raise DomainError("validation_failed", message="Audio sample rate or channel count is unsupported.")
        expected_extension = ".ogg" if output_format == "opus" else f".{output_format}"
        if Path(output_path).suffix.lower() != expected_extension:
            raise DomainError("validation_failed", message="Audio destination extension must match output format.")
        codec, mime = AUDIO_FORMATS[output_format]
        normalized = {"kind": "audio", "format": output_format, "sample_rate": sample_rate, "channels": channels}
        args = ["-map_metadata", "-1", "-vn", "-ar", str(sample_rate), "-ac", str(channels), "-c:a", codec]
        return await self._execute(session, asset_id, output_path, normalized, args, "audio", mime, timeout_seconds, execution_id)

    async def waveform(self, session, asset_id: str, output_path: str, parameters: dict[str, Any], timeout_seconds: float = 120, execution_id: str | None = None):
        width = self._dimension(parameters.get("width") or 1200, "width")
        height = self._dimension(parameters.get("height") or 240, "height")
        color = str(parameters.get("color") or "#4f46e5")
        if not color.startswith("#") or len(color) not in {4, 7} or any(character not in "0123456789abcdefABCDEF" for character in color[1:]):
            raise DomainError("validation_failed", message="Waveform color is invalid.")
        if Path(output_path).suffix.lower() != ".png":
            raise DomainError("validation_failed", message="Waveform destination must be PNG.")
        normalized = {"kind": "waveform", "format": "png", "width": width, "height": height, "color": color.lower()}
        args = ["-filter_complex", f"showwavespic=s={width}x{height}:colors={color}", "-frames:v", "1", "-map_metadata", "-1", "-c:v", "png"]
        return await self._execute(session, asset_id, output_path, normalized, args, "raster", "image/png", timeout_seconds, execution_id)

    async def _execute(self, session, asset_id: str, output_path: str, parameters: dict[str, Any], transform_args: list[str], asset_type: str, mime: str, timeout_seconds: float, execution_id: str | None):
        if not 1 <= timeout_seconds <= 1800:
            raise DomainError("validation_failed", message="Media transform timeout is invalid.")
        original = await session.get(AssetRecord, asset_id)
        if not original:
            raise DomainError("resource_not_found", message="Original asset was not found.")
        workspace = await session.get(WorkspaceRecord, original.workspace_id)
        if not workspace:
            raise DomainError("resource_not_found", message="Asset workspace was not found.")
        try:
            root = path_policy.existing_directory(workspace.path)
            source = path_policy.contained_file(root, root / original.relative_path)
            destination = self._destination(root, output_path)
        except PathPolicyError as exc:
            raise DomainError("validation_failed", message=str(exc)) from exc
        if not self.ffmpeg or not self.ffprobe:
            raise DomainError("execution_unavailable", message="FFmpeg and ffprobe are required for this transform.")
        input_hash = self._hash(source)
        if input_hash != original.sha256:
            raise DomainError("resource_conflict", message="Original asset content no longer matches its recorded hash.")
        kind = parameters["kind"]
        if kind == "image" and original.asset_type != "raster" or kind in {"audio", "waveform"} and original.asset_type != "audio":
            raise DomainError("validation_failed", message="Asset type is incompatible with the requested transform.")
        if destination.exists():
            raise DomainError("resource_conflict", message="Transform destination already exists.")
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp{destination.suffix}")
        job = AssetTransformJobRecord(id=f"transform-{uuid.uuid4().hex[:12]}", original_asset_id=original.id, tool="ffmpeg", tool_version=await self._version(), parameters_json=json.dumps(parameters, sort_keys=True), status="running", input_hash=input_hash, provenance="deterministic_transform")
        session.add(job)
        await session.commit()
        task_id = execution_id or f"media-{job.id}"
        try:
            receipt = await self.manager.execute_argv([self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), *transform_args, str(temporary)], task_id=task_id, cwd=str(root), timeout_seconds=timeout_seconds)
            if receipt["outcome"] != "completed" or not temporary.is_file() or temporary.stat().st_size == 0:
                raise DomainError(receipt.get("error_code") if receipt.get("error_code") in {"execution_timeout", "execution_cancelled"} else "execution_unavailable", message="Media transform failed.", details={"outcome": receipt.get("outcome"), "stderr": (receipt.get("stderr") or "")[-1000:]})
            probe = await self._probe(temporary, root, timeout_seconds)
            temporary.replace(destination)
            output_hash = self._hash(destination)
            derivative = AssetRecord(id=f"asset-{uuid.uuid4().hex[:12]}", scope_type=original.scope_type, project_id=original.project_id, workspace_id=workspace.id, relative_path=destination.relative_to(root).as_posix(), asset_type=asset_type, mime_type=mime, sha256=output_hash, source_type="transform", source_id=job.id, provenance="deterministic_transform", license_id=original.license_id, width=probe.get("width"), height=probe.get("height"), duration_ms=probe.get("duration_ms"), size_bytes=destination.stat().st_size, state="ready", metadata_json=json.dumps({"original_asset_id": original.id, "transform_job_id": job.id, "ffprobe": probe}, sort_keys=True))
            session.add(derivative)
            job.derivative_asset_id = derivative.id
            job.output_hash = output_hash
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            await session.commit()
            return {"job": job.to_dict(), "asset": derivative.to_dict(), "receipt": {key: receipt.get(key) for key in ("task_id", "outcome", "exit_code", "duration_ms")}}
        except BaseException:
            temporary.unlink(missing_ok=True)
            job.status = "cancelled" if self.manager.get_receipt(task_id) and self.manager.get_receipt(task_id).get("outcome") == "cancelled" else "failed"
            job.completed_at = datetime.utcnow()
            await session.commit()
            raise

    async def _version(self) -> str:
        receipt = await self.manager.execute_argv([self.ffmpeg, "-version"], task_id=f"ffmpeg-version-{uuid.uuid4().hex[:10]}", timeout_seconds=10)
        if receipt["outcome"] != "completed":
            raise DomainError("execution_unavailable", message="FFmpeg version probe failed.")
        first = receipt.get("stdout", "").splitlines()[0]
        return first.split("version", 1)[-1].strip().split()[0][:64]

    async def _probe(self, path: Path, root: Path, timeout: float) -> dict[str, Any]:
        receipt = await self.manager.execute_argv([self.ffprobe, "-v", "error", "-show_entries", "stream=width,height:format=duration", "-of", "json", str(path)], task_id=f"ffprobe-{uuid.uuid4().hex[:12]}", cwd=str(root), timeout_seconds=min(timeout, 30))
        if receipt["outcome"] != "completed":
            raise DomainError("execution_unavailable", message="Transformed media validation failed.")
        try:
            payload = json.loads(receipt.get("stdout") or "{}")
            stream = next((item for item in payload.get("streams", []) if item.get("width") or item.get("height")), {})
            duration = float(payload.get("format", {}).get("duration") or 0)
            return {"width": stream.get("width"), "height": stream.get("height"), "duration_ms": round(duration * 1000) if duration > 0 else None}
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise DomainError("execution_unavailable", message="Transformed media metadata is invalid.") from exc

    def _destination(self, root: Path, relative: str) -> Path:
        if not relative or "\x00" in relative or Path(relative).is_absolute():
            raise PathPolicyError("Transform destination is invalid.")
        parent = (root / relative).parent.resolve(strict=True)
        destination = parent / Path(relative).name
        if root != parent and root not in parent.parents:
            raise PathPolicyError("Transform destination is outside the approved workspace.")
        return destination

    def _dimension(self, value: Any, name: str) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 16384:
            raise DomainError("validation_failed", message=f"Image {name} is invalid.")
        return value

    def _nonnegative(self, value: Any, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 16384:
            raise DomainError("validation_failed", message=f"Image crop {name} is invalid.")
        return value

    def _hash(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(65536):
                digest.update(chunk)
        return digest.hexdigest()
