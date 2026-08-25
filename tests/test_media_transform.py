import asyncio
import hashlib
import json
import struct
import zlib
import shutil
import tempfile
import unittest
import uuid
import wave
from pathlib import Path

from sqlalchemy import delete

from core.ai_fleet.engine.process_manager import ProcessManager
from core.ai_fleet.errors import DomainError
from core.ai_fleet.services.media_transform import MediaTransformService
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import AssetRecord, AssetTransformJobRecord, WorkspaceRecord


def png(width=2, height=2):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    rows = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


PNG = png()


class CancelManager:
    def __init__(self):
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.receipt = None

    async def execute_argv(self, args, task_id, **kwargs):
        if "-version" in args:
            return {"task_id": task_id, "outcome": "completed", "error_code": None, "exit_code": 0, "duration_ms": 1, "stdout": "ffmpeg version 8.1.1 test"}
        self.started.set()
        await self.cancelled.wait()
        self.receipt = {"task_id": task_id, "outcome": "cancelled", "error_code": "execution_cancelled", "exit_code": -1, "duration_ms": 1}
        return self.receipt

    async def cancel(self, task_id):
        self.cancelled.set()
        return True

    def get_receipt(self, task_id):
        return self.receipt


class MediaTransformTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("FFmpeg fixtures require ffmpeg and ffprobe")
        await init_db()
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name).resolve()
        (self.root / "variants").mkdir()
        self.workspace_id = f"media-workspace-{uuid.uuid4().hex[:8]}"
        self.image_id = f"media-image-{uuid.uuid4().hex[:8]}"
        self.audio_id = f"media-audio-{uuid.uuid4().hex[:8]}"
        (self.root / "source.png").write_bytes(PNG)
        with wave.open(str(self.root / "source.wav"), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"\x00\x00" * 8000)
        async with AsyncSessionLocal() as session:
            session.add(WorkspaceRecord(id=self.workspace_id, name="Media", path=str(self.root), permission_profile="developer", allowed_shells="[]"))
            session.add(self.asset(self.image_id, "source.png", "raster", "image/png"))
            session.add(self.asset(self.audio_id, "source.wav", "audio", "audio/wav"))
            await session.commit()
        self.service = MediaTransformService(ProcessManager())
        self.derivative_ids = []

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            jobs = (await session.execute(__import__("sqlalchemy").select(AssetTransformJobRecord).where(AssetTransformJobRecord.original_asset_id.in_([self.image_id, self.audio_id])))).scalars().all()
            derivative_ids = [job.derivative_asset_id for job in jobs if job.derivative_asset_id]
            await session.execute(delete(AssetTransformJobRecord).where(AssetTransformJobRecord.original_asset_id.in_([self.image_id, self.audio_id])))
            if derivative_ids:
                await session.execute(delete(AssetRecord).where(AssetRecord.id.in_(derivative_ids)))
            await session.execute(delete(AssetRecord).where(AssetRecord.id.in_([self.image_id, self.audio_id])))
            await session.execute(delete(WorkspaceRecord).where(WorkspaceRecord.id == self.workspace_id))
            await session.commit()
        self.folder.cleanup()

    def asset(self, asset_id, relative, asset_type, mime):
        path = self.root / relative
        return AssetRecord(id=asset_id, scope_type="global", workspace_id=self.workspace_id, relative_path=relative, asset_type=asset_type, mime_type=mime, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), source_type="user", provenance="owner_declared", size_bytes=path.stat().st_size, state="ready")

    async def test_image_resize_and_format_preserve_original_and_lineage(self):
        original = (self.root / "source.png").read_bytes()
        async with AsyncSessionLocal() as session:
            result = await self.service.image(session, self.image_id, "variants/thumb.webp", {"format": "webp", "width": 16, "height": 12})
        derivative = result["asset"]
        self.assertEqual((derivative["width"], derivative["height"]), (16, 12))
        self.assertEqual(derivative["mime_type"], "image/webp")
        self.assertEqual((self.root / "source.png").read_bytes(), original)
        self.assertEqual(hashlib.sha256((self.root / derivative["relative_path"]).read_bytes()).hexdigest(), derivative["sha256"])
        self.assertEqual(result["job"]["parameters"]["width"], 16)
        self.assertEqual(result["job"]["input_hash"], hashlib.sha256(original).hexdigest())
        async with AsyncSessionLocal() as session:
            repeat = await self.service.image(session, self.image_id, "variants/thumb-repeat.webp", {"format": "webp", "width": 16, "height": 12})
            contained = await self.service.image(session, self.image_id, "variants/contained.png", {"format": "png", "width": 20, "height": 10, "fit": "contain", "quality": 90})
        self.assertEqual(repeat["asset"]["sha256"], derivative["sha256"])
        self.assertEqual((contained["asset"]["width"], contained["asset"]["height"]), (20, 10))

    async def test_audio_conversion_and_waveform_retain_metadata(self):
        async with AsyncSessionLocal() as session:
            converted = await self.service.audio(session, self.audio_id, "variants/audio.mp3", {"format": "mp3", "sample_rate": 16000, "channels": 1})
            waveform = await self.service.waveform(session, self.audio_id, "variants/waveform.png", {"width": 320, "height": 80, "color": "#112233"})
        self.assertEqual(converted["asset"]["mime_type"], "audio/mpeg")
        self.assertGreaterEqual(converted["asset"]["duration_ms"], 900)
        self.assertEqual((waveform["asset"]["width"], waveform["asset"]["height"]), (320, 80))
        self.assertEqual(waveform["job"]["parameters"]["color"], "#112233")
        self.assertTrue((self.root / "source.wav").is_file())

    async def test_invalid_paths_parameters_and_hash_drift_are_rejected(self):
        async with AsyncSessionLocal() as session:
            with self.assertRaises(DomainError):
                await self.service.image(session, self.image_id, "../escape.png", {"format": "png", "width": 10})
            with self.assertRaises(DomainError):
                await self.service.audio(session, self.audio_id, "bad.mp3", {"format": "mp3", "sample_rate": 12345})
            (self.root / "source.png").write_bytes(PNG + b"drift")
            with self.assertRaisesRegex(DomainError, "recorded hash"):
                await self.service.image(session, self.image_id, "drift.webp", {"format": "webp", "width": 10})

    async def test_cancellation_marks_job_and_removes_temporary_output(self):
        manager = CancelManager()
        service = MediaTransformService(manager, shutil.which("ffmpeg"), shutil.which("ffprobe"))
        async with AsyncSessionLocal() as session:
            task = asyncio.create_task(service.audio(session, self.audio_id, "cancelled.mp3", {"format": "mp3"}, execution_id="cancel-media-test"))
            await manager.started.wait()
            self.assertTrue(await manager.cancel("cancel-media-test"))
            with self.assertRaises(DomainError):
                await task
            jobs = (await session.execute(__import__("sqlalchemy").select(AssetTransformJobRecord).where(AssetTransformJobRecord.original_asset_id == self.audio_id))).scalars().all()
            self.assertEqual(jobs[-1].status, "cancelled")
        self.assertFalse((self.root / "cancelled.mp3").exists())
        self.assertEqual(list(self.root.glob(".cancelled.mp3.*")), [])


if __name__ == "__main__":
    unittest.main()
