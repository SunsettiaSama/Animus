from __future__ import annotations

import asyncio
import importlib.machinery
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))


# ── Stub 重量级外部依赖（必须在导入 tts 模块之前） ──────────────────────────


def _pkg_stub(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    m.__package__ = name
    m.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
    m.__path__ = []
    sys.modules[name] = m
    return m


def _mod_stub(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m


# edge-tts
_edge_tts = _pkg_stub("edge_tts")
_fake_communicate_cls = MagicMock(name="Communicate")
_edge_tts.Communicate = _fake_communicate_cls

# faster-whisper
_fw = _pkg_stub("faster_whisper")
_fw.WhisperModel = MagicMock(name="WhisperModel")

# kokoro
_kokoro = _pkg_stub("kokoro")
_kokoro.KPipeline = MagicMock(name="KPipeline")

# soundfile / numpy (used by KokoroProvider)
_sf = _mod_stub("soundfile")
_np = _mod_stub("numpy")
_np.array = MagicMock(name="np.array", return_value=b"")
_sf.write = MagicMock(name="sf.write")

# httpx (already installed, but we mock it anyway for offline tests)
import httpx as _real_httpx  # noqa: E402

# ── 现在安全导入 tts 相关模块 ─────────────────────────────────────────────────

from config.tts.tts_config import TTSConfig
from config.tts.stt_config import STTConfig
from tts.tts.base import BaseTTSProvider
from tts.tts.engine import TTSEngine
from tts.stt.base import BaseSTTProvider
from tts.stt.engine import STTEngine
from tts.tts.providers.edge import EdgeTTSProvider
from tts.tts.providers.openai_tts import OpenAITTSProvider
from tts.tts.providers.kokoro import KokoroProvider
from tts.stt.providers.openai_stt import OpenAISTTProvider
from tts.stt.providers.faster_whisper import FasterWhisperProvider


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _tts_cfg(**kw) -> TTSConfig:
    defaults = dict(
        provider="edge",
        voice="zh-CN-XiaoxiaoNeural",
        rate="+0%",
        volume="+0%",
        output_format="mp3",
        openai_model="tts-1",
        openai_base_url="http://test-host",
        openai_api_key="sk-test",
        kokoro_model_path="",
        kokoro_device="cpu",
    )
    defaults.update(kw)
    return TTSConfig(**defaults)


def _stt_cfg(**kw) -> STTConfig:
    defaults = dict(
        provider="openai",
        language="zh",
        output_format="text",
        openai_model="whisper-1",
        openai_base_url="http://test-host",
        openai_api_key="sk-test",
        local_model_size="base",
        local_model_path="",
        local_device="cpu",
        local_compute_type="int8",
    )
    defaults.update(kw)
    return STTConfig(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# 1. 配置层单元测试
# ─────────────────────────────────────────────────────────────────────────────


class TestTTSConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = TTSConfig()
        self.assertEqual(cfg.provider, "edge")
        self.assertEqual(cfg.voice, "zh-CN-XiaoxiaoNeural")
        self.assertEqual(cfg.rate, "+0%")
        self.assertEqual(cfg.output_format, "mp3")

    def test_from_dict_partial(self):
        cfg = TTSConfig.from_dict({"provider": "openai", "voice": "alloy"})
        self.assertEqual(cfg.provider, "openai")
        self.assertEqual(cfg.voice, "alloy")
        self.assertEqual(cfg.openai_model, "tts-1")

    def test_from_dict_empty(self):
        cfg = TTSConfig.from_dict({})
        self.assertIsInstance(cfg, TTSConfig)

    def test_from_yaml(self):
        import tempfile, yaml, os
        data = {"provider": "openai", "voice": "shimmer", "openai_api_key": "sk-abc"}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(data, f)
            fname = f.name
        cfg = TTSConfig.from_yaml(fname)
        os.unlink(fname)
        self.assertEqual(cfg.provider, "openai")
        self.assertEqual(cfg.voice, "shimmer")
        self.assertEqual(cfg.openai_api_key, "sk-abc")


class TestSTTConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = STTConfig()
        self.assertEqual(cfg.provider, "openai")
        self.assertEqual(cfg.language, "zh")
        self.assertEqual(cfg.output_format, "text")
        self.assertEqual(cfg.local_model_size, "base")

    def test_from_dict_partial(self):
        cfg = STTConfig.from_dict({"provider": "faster_whisper", "local_model_size": "small"})
        self.assertEqual(cfg.provider, "faster_whisper")
        self.assertEqual(cfg.local_model_size, "small")
        self.assertEqual(cfg.language, "zh")

    def test_from_dict_empty(self):
        cfg = STTConfig.from_dict({})
        self.assertIsInstance(cfg, STTConfig)

    def test_from_yaml(self):
        import tempfile, yaml, os
        data = {"provider": "faster_whisper", "local_device": "cuda", "local_model_size": "large"}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(data, f)
            fname = f.name
        cfg = STTConfig.from_yaml(fname)
        os.unlink(fname)
        self.assertEqual(cfg.provider, "faster_whisper")
        self.assertEqual(cfg.local_device, "cuda")
        self.assertEqual(cfg.local_model_size, "large")


# ─────────────────────────────────────────────────────────────────────────────
# 2. TTSEngine 路由测试
# ─────────────────────────────────────────────────────────────────────────────


class TestTTSEngineRouting(unittest.TestCase):
    def test_from_config_edge(self):
        cfg = _tts_cfg(provider="edge")
        engine = TTSEngine.from_config(cfg)
        self.assertIsInstance(engine._provider, EdgeTTSProvider)

    def test_from_config_openai(self):
        cfg = _tts_cfg(provider="openai")
        engine = TTSEngine.from_config(cfg)
        self.assertIsInstance(engine._provider, OpenAITTSProvider)

    def test_from_config_kokoro(self):
        cfg = _tts_cfg(provider="kokoro")
        engine = TTSEngine.from_config(cfg)
        self.assertIsInstance(engine._provider, KokoroProvider)

    def test_from_config_unknown_raises(self):
        cfg = _tts_cfg(provider="nonexistent")
        self.assertRaises(ValueError, TTSEngine.from_config, cfg)

    def test_stream_delegates_to_provider(self):
        cfg = _tts_cfg(provider="edge")
        engine = TTSEngine.from_config(cfg)

        async def _fake_stream(text):
            yield b"chunk1"
            yield b"chunk2"

        engine._provider.stream = _fake_stream

        async def _collect():
            chunks = []
            async for c in engine.stream("hello"):
                chunks.append(c)
            return chunks

        result = _run(_collect())
        self.assertEqual(result, [b"chunk1", b"chunk2"])

    def test_synthesize_delegates_to_provider(self):
        cfg = _tts_cfg(provider="edge")
        engine = TTSEngine.from_config(cfg)
        engine._provider.synthesize = AsyncMock(return_value=b"audio-bytes")
        result = _run(engine.synthesize("hello"))
        self.assertEqual(result, b"audio-bytes")


# ─────────────────────────────────────────────────────────────────────────────
# 3. STTEngine 路由测试
# ─────────────────────────────────────────────────────────────────────────────


class TestSTTEngineRouting(unittest.TestCase):
    def test_from_config_openai(self):
        cfg = _stt_cfg(provider="openai")
        engine = STTEngine.from_config(cfg)
        self.assertIsInstance(engine._provider, OpenAISTTProvider)

    def test_from_config_faster_whisper(self):
        cfg = _stt_cfg(provider="faster_whisper")
        engine = STTEngine.from_config(cfg)
        self.assertIsInstance(engine._provider, FasterWhisperProvider)

    def test_from_config_unknown_raises(self):
        cfg = _stt_cfg(provider="unknown_backend")
        self.assertRaises(ValueError, STTEngine.from_config, cfg)

    def test_transcribe_delegates_to_provider(self):
        cfg = _stt_cfg(provider="openai")
        engine = STTEngine.from_config(cfg)
        engine._provider.transcribe = AsyncMock(return_value="转录结果")
        result = _run(engine.transcribe(b"audio", "audio/webm"))
        engine._provider.transcribe.assert_called_once_with(b"audio", "audio/webm")
        self.assertEqual(result, "转录结果")


# ─────────────────────────────────────────────────────────────────────────────
# 4. BaseTTSProvider.synthesize 默认实现
# ─────────────────────────────────────────────────────────────────────────────


class _ConcreteProvider(BaseTTSProvider):
    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks

    async def stream(self, text: str):
        for c in self._chunks:
            yield c


class TestBaseTTSProviderSynthesize(unittest.TestCase):
    def test_synthesize_joins_stream_chunks(self):
        p = _ConcreteProvider([b"hello", b" ", b"world"])
        result = _run(p.synthesize("any text"))
        self.assertEqual(result, b"hello world")

    def test_synthesize_empty_stream(self):
        p = _ConcreteProvider([])
        result = _run(p.synthesize("empty"))
        self.assertEqual(result, b"")

    def test_synthesize_single_chunk(self):
        p = _ConcreteProvider([b"\xff\xfb\x90\x00"])
        result = _run(p.synthesize("x"))
        self.assertEqual(result, b"\xff\xfb\x90\x00")


# ─────────────────────────────────────────────────────────────────────────────
# 5. EdgeTTSProvider
# ─────────────────────────────────────────────────────────────────────────────


class TestEdgeTTSProvider(unittest.TestCase):
    def _make_communicate(self, audio_chunks: list[bytes]):
        comm = MagicMock()

        async def _fake_stream():
            for chunk in audio_chunks:
                yield {"type": "audio", "data": chunk}
            yield {"type": "WordBoundary", "data": b""}  # non-audio, must be ignored

        comm.stream = _fake_stream
        _fake_communicate_cls.return_value = comm
        return comm

    def test_stream_yields_audio_chunks(self):
        self._make_communicate([b"frame1", b"frame2"])
        cfg = _tts_cfg(provider="edge")
        provider = EdgeTTSProvider(cfg)

        async def _collect():
            chunks = []
            async for c in provider.stream("test text"):
                chunks.append(c)
            return chunks

        result = _run(_collect())
        self.assertEqual(result, [b"frame1", b"frame2"])

    def test_stream_skips_non_audio_events(self):
        self._make_communicate([b"only-audio"])
        cfg = _tts_cfg(provider="edge")
        provider = EdgeTTSProvider(cfg)

        async def _collect():
            return [c async for c in provider.stream("x")]

        result = _run(_collect())
        self.assertEqual(len(result), 1)

    def test_synthesize_joins_all_chunks(self):
        self._make_communicate([b"ABC", b"DEF"])
        cfg = _tts_cfg(provider="edge")
        provider = EdgeTTSProvider(cfg)
        result = _run(provider.synthesize("hello"))
        self.assertEqual(result, b"ABCDEF")

    def test_communicate_called_with_correct_voice(self):
        comm = self._make_communicate([b"x"])
        cfg = _tts_cfg(provider="edge", voice="en-US-JennyNeural", rate="+10%", volume="-5%")
        provider = EdgeTTSProvider(cfg)
        _run(provider.synthesize("hi"))
        _fake_communicate_cls.assert_called_with(
            text="hi",
            voice="en-US-JennyNeural",
            rate="+10%",
            volume="-5%",
        )


# ─────────────────────────────────────────────────────────────────────────────
# 6. OpenAITTSProvider
# ─────────────────────────────────────────────────────────────────────────────


class TestOpenAITTSProvider(unittest.TestCase):
    def _make_provider(self, **kw) -> OpenAITTSProvider:
        cfg = _tts_cfg(provider="openai", **kw)
        return OpenAITTSProvider(cfg)

    def test_synthesize_returns_audio_bytes(self):
        provider = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.content = b"mp3-data"
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(provider.synthesize("hello world"))

        self.assertEqual(result, b"mp3-data")
        mock_client.post.assert_called_once()

    def test_synthesize_sends_correct_payload(self):
        provider = self._make_provider(voice="nova", openai_model="tts-1-hd")
        mock_resp = MagicMock()
        mock_resp.content = b"audio"
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            _run(provider.synthesize("test"))

        call_kwargs = mock_client.post.call_args
        body = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        self.assertEqual(body["model"], "tts-1-hd")
        self.assertEqual(body["voice"], "nova")
        self.assertEqual(body["input"], "test")

    def test_stream_yields_chunks(self):
        provider = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        async def _fake_iter(size):
            yield b"part1"
            yield b"part2"

        mock_resp.aiter_bytes = _fake_iter
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            async def _collect():
                return [c async for c in provider.stream("hello")]

            result = _run(_collect())

        self.assertEqual(result, [b"part1", b"part2"])


# ─────────────────────────────────────────────────────────────────────────────
# 7. OpenAISTTProvider
# ─────────────────────────────────────────────────────────────────────────────


class TestOpenAISTTProvider(unittest.TestCase):
    def _make_provider(self, **kw) -> OpenAISTTProvider:
        cfg = _stt_cfg(provider="openai", **kw)
        return OpenAISTTProvider(cfg)

    def test_transcribe_returns_text(self):
        provider = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.text = "这是转录结果\n"
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(provider.transcribe(b"audio-bytes", "audio/wav"))

        self.assertEqual(result, "这是转录结果")

    def test_transcribe_json_format(self):
        provider = self._make_provider(output_format="verbose_json")
        mock_resp = MagicMock()
        mock_resp.json = MagicMock(return_value={"text": "json text result"})
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(provider.transcribe(b"audio", "audio/webm"))

        self.assertEqual(result, "json text result")

    def test_mime_to_extension_mapping(self):
        provider = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.text = "ok"
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            _run(provider.transcribe(b"audio", "audio/mp3"))

        call_kwargs = mock_client.post.call_args[1]
        files = call_kwargs["files"]
        filename = files["file"][0]
        self.assertTrue(filename.endswith(".mp3"), f"expected .mp3, got {filename}")

    def test_transcribe_sends_correct_model_and_language(self):
        provider = self._make_provider(openai_model="whisper-1", language="en")
        mock_resp = MagicMock()
        mock_resp.text = "result"
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            _run(provider.transcribe(b"audio", "audio/wav"))

        call_kwargs = mock_client.post.call_args[1]
        data = call_kwargs["data"]
        self.assertEqual(data["model"], "whisper-1")
        self.assertEqual(data["language"], "en")


# ─────────────────────────────────────────────────────────────────────────────
# 8. FasterWhisperProvider
# ─────────────────────────────────────────────────────────────────────────────


class TestFasterWhisperProvider(unittest.TestCase):
    def _make_provider(self, **kw) -> FasterWhisperProvider:
        cfg = _stt_cfg(provider="faster_whisper", **kw)
        return FasterWhisperProvider(cfg)

    def _setup_mock_model(self, segments_text: list[str]):
        segments = [MagicMock(text=t) for t in segments_text]
        mock_model = MagicMock()
        mock_model.transcribe = MagicMock(return_value=(iter(segments), MagicMock()))
        _fw.WhisperModel.return_value = mock_model
        return mock_model

    def test_transcribe_joins_segments(self):
        self._setup_mock_model(["Hello ", "world"])
        provider = self._make_provider()

        with patch("tempfile.NamedTemporaryFile") as mock_tmp, \
             patch("os.unlink"):
            mock_file = MagicMock()
            mock_file.__enter__ = MagicMock(return_value=mock_file)
            mock_file.__exit__ = MagicMock(return_value=False)
            mock_file.name = "/tmp/fake.wav"
            mock_tmp.return_value = mock_file

            result = _run(provider.transcribe(b"audio", "audio/wav"))

        self.assertEqual(result, "Hello world")

    def test_transcribe_strips_whitespace(self):
        self._setup_mock_model(["  trimmed  "])
        provider = self._make_provider()

        with patch("tempfile.NamedTemporaryFile") as mock_tmp, \
             patch("os.unlink"):
            mock_file = MagicMock()
            mock_file.__enter__ = MagicMock(return_value=mock_file)
            mock_file.__exit__ = MagicMock(return_value=False)
            mock_file.name = "/tmp/fake.wav"
            mock_tmp.return_value = mock_file

            result = _run(provider.transcribe(b"audio"))

        self.assertEqual(result, "trimmed")

    def test_model_loaded_lazily(self):
        _fw.WhisperModel.reset_mock()
        provider = self._make_provider()
        _fw.WhisperModel.assert_not_called()

    def test_model_loaded_once(self):
        self._setup_mock_model(["a"])
        provider = self._make_provider()

        _fw.WhisperModel.reset_mock()
        _fw.WhisperModel.return_value = self._setup_mock_model(["a"])

        call_count_before = _fw.WhisperModel.call_count

        with patch("tempfile.NamedTemporaryFile") as mock_tmp, \
             patch("os.unlink"):
            mock_file = MagicMock()
            mock_file.__enter__ = MagicMock(return_value=mock_file)
            mock_file.__exit__ = MagicMock(return_value=False)
            mock_file.name = "/tmp/fake.wav"
            mock_tmp.return_value = mock_file

            _run(provider.transcribe(b"audio"))
            _fw.WhisperModel.reset_mock()
            mock_model = MagicMock()
            mock_model.transcribe = MagicMock(return_value=(iter([MagicMock(text="b")]), MagicMock()))
            provider._model = mock_model
            _run(provider.transcribe(b"audio"))

        _fw.WhisperModel.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 9. KokoroProvider
# ─────────────────────────────────────────────────────────────────────────────


class TestKokoroProvider(unittest.TestCase):
    def _make_provider(self, **kw) -> KokoroProvider:
        cfg = _tts_cfg(provider="kokoro", **kw)
        return KokoroProvider(cfg)

    def _setup_mock_pipeline(self, wav_bytes: bytes = b"WAV"):
        fake_audio = MagicMock()
        mock_pipeline = MagicMock()
        mock_pipeline.return_value = [(None, None, fake_audio)]
        _kokoro.KPipeline.return_value = mock_pipeline

        def _fake_sf_write(buf, arr, sr, format):
            buf.write(wav_bytes)

        _sf.write.side_effect = _fake_sf_write
        return mock_pipeline

    def test_pipeline_loaded_lazily(self):
        _kokoro.KPipeline.reset_mock()
        provider = self._make_provider()
        _kokoro.KPipeline.assert_not_called()

    def test_synthesize_returns_bytes(self):
        self._setup_mock_pipeline(b"FAKEAUDIO")
        provider = self._make_provider()
        result = _run(provider.synthesize("你好"))
        self.assertIsInstance(result, bytes)

    def test_stream_yields_chunks(self):
        self._setup_mock_pipeline(b"X" * 10000)
        provider = self._make_provider()

        async def _collect():
            chunks = []
            async for c in provider.stream("text"):
                chunks.append(c)
            return chunks

        result = _run(_collect())
        self.assertGreater(len(result), 0)
        self.assertEqual(b"".join(result), b"X" * 10000)

    def test_stream_uses_4096_chunk_size(self):
        self._setup_mock_pipeline(b"A" * 8192)
        provider = self._make_provider()

        async def _collect():
            return [c async for c in provider.stream("text")]

        chunks = _run(_collect())
        for chunk in chunks[:-1]:
            self.assertEqual(len(chunk), 4096)


# ─────────────────────────────────────────────────────────────────────────────
# 10. 顶层 __init__ 导出
# ─────────────────────────────────────────────────────────────────────────────


class TestTTSPackageExports(unittest.TestCase):
    def test_tts_engine_importable(self):
        from tts import TTSEngine as _T
        self.assertIs(_T, TTSEngine)

    def test_stt_engine_importable(self):
        from tts import STTEngine as _S
        self.assertIs(_S, STTEngine)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
