# TTS / STT

`src/tts/` 模块提供语音合成（TTS）和语音识别（STT）能力，通过统一的 Engine 接口屏蔽底层 Provider 差异。

---

## 目录结构

```
src/tts/
  ├── tts/
  │   ├── engine.py          # TTSEngine：统一合成入口
  │   ├── base.py            # BaseTTSProvider 抽象类
  │   └── providers/
  │       ├── edge.py        # EdgeTTSProvider（微软云，默认）
  │       ├── openai_tts.py  # OpenAITTSProvider
  │       └── kokoro.py      # KokoroProvider（本地）
  └── stt/
      ├── engine.py          # STTEngine：统一识别入口
      ├── base.py            # BaseSTTProvider 抽象类
      └── providers/
          ├── openai_stt.py      # OpenAISTTProvider
          └── faster_whisper.py  # FasterWhisperProvider（本地）
```

配置文件：[`src/config/tts/tts_config.py`](../../src/config/tts/tts_config.py)、[`src/config/tts/stt_config.py`](../../src/config/tts/stt_config.py)

---

## TTSEngine

文件：[`src/tts/tts/engine.py`](../../src/tts/tts/engine.py)

### 创建

```python
from tts.tts.engine import TTSEngine
from config.tts.tts_config import TTSConfig

engine = TTSEngine.from_config(cfg)          # 从 TTSConfig 实例创建
engine = TTSEngine.from_yaml("config/tts/tts.yaml")  # 从 YAML 创建
```

`from_config` 根据 `cfg.provider` 分发到对应 Provider：

| `cfg.provider` | Provider 类 |
|---|---|
| `"edge"` | `EdgeTTSProvider` |
| `"openai"` | `OpenAITTSProvider` |
| `"kokoro"` | `KokoroProvider` |

### 方法

| 方法 | 签名 | 说明 |
|---|---|---|
| `stream` | `async (text: str) -> AsyncIterator[bytes]` | 流式合成，用于 WebSocket 实时播放 |
| `synthesize` | `async (text: str) -> bytes` | 一次性合成完整音频，用于 REST 接口 |

---

## STTEngine

文件：[`src/tts/stt/engine.py`](../../src/tts/stt/engine.py)

### 创建

```python
from tts.stt.engine import STTEngine
from config.tts.stt_config import STTConfig

engine = STTEngine.from_config(cfg)
engine = STTEngine.from_yaml("config/tts/stt.yaml")
```

`from_config` 根据 `cfg.provider` 分发：

| `cfg.provider` | Provider 类 |
|---|---|
| `"openai"` | `OpenAISTTProvider` |
| `"faster_whisper"` | `FasterWhisperProvider` |

### 方法

| 方法 | 签名 | 说明 |
|---|---|---|
| `transcribe` | `async (audio: bytes, mime_type="audio/webm") -> str` | 将音频字节转换为文本 |

---

## Provider 对比

| Provider | 类型 | 依赖包 | 网络 | 说明 |
|---|---|---|---|---|
| `edge` | TTS | `edge-tts` | 需联网 | 微软 Azure 云端合成，无需 API Key，默认方案 |
| `openai` | TTS | `openai` | 需联网 | 调用 OpenAI `tts-1` 等模型，支持自定义 base_url |
| `kokoro` | TTS | `kokoro` | 可离线 | 本地或自部署端点，模型从 HuggingFace 下载 |
| `openai` | STT | `openai` | 需联网 | 调用 OpenAI `whisper-1`，支持自定义 base_url |
| `faster_whisper` | STT | `faster-whisper` | 可离线 | 本地 CTranslate2 推理，支持 int8 量化 |

---

## TTSConfig 字段

文件：[`src/config/tts/tts_config.py`](../../src/config/tts/tts_config.py)

| 字段 | 默认值 | 说明 |
|---|---|---|
| `provider` | `"edge"` | TTS 后端：`edge` / `openai` / `kokoro` |
| `voice` | `"zh-CN-XiaoxiaoNeural"` | 语音名称（edge / OpenAI 通用） |
| `rate` | `"+0%"` | 语速调整（edge 专用，如 `+20%`） |
| `volume` | `"+0%"` | 音量调整（edge 专用） |
| `output_format` | `"mp3"` | 输出音频格式 |
| `openai_model` | `"tts-1"` | OpenAI TTS 模型名 |
| `openai_base_url` | `""` | OpenAI 兼容 API 地址（可选） |
| `openai_api_key` | `""` | OpenAI API Key |
| `kokoro_model_path` | `""` | Kokoro 本地模型路径（空则从 HF 下载） |
| `kokoro_device` | `"auto"` | `auto` / `cuda` / `cpu` |
| `kokoro_hf_repo_id` | `"hexgrad/Kokoro-82M"` | Kokoro HuggingFace 模型仓库 |
| `hf_endpoint` | `""` | HF 镜像地址（如 `https://hf-mirror.com`） |
| `hf_token` | `""` | HuggingFace 访问 Token |

---

## STTConfig 字段

文件：[`src/config/tts/stt_config.py`](../../src/config/tts/stt_config.py)

| 字段 | 默认值 | 说明 |
|---|---|---|
| `provider` | `"openai"` | STT 后端：`openai` / `faster_whisper` |
| `language` | `"zh"` | 识别语言 |
| `output_format` | `"text"` | 输出格式 |
| `openai_model` | `"whisper-1"` | OpenAI STT 模型名 |
| `openai_base_url` | `""` | OpenAI 兼容 API 地址（可选） |
| `openai_api_key` | `""` | OpenAI API Key |
| `local_model_size` | `"base"` | faster-whisper 模型规格：`tiny`/`base`/`small`/`medium`/`large` |
| `local_model_path` | `""` | 本地模型路径（空则自动下载） |
| `local_device` | `"auto"` | `auto` / `cuda` / `cpu` |
| `local_compute_type` | `"int8"` | 量化类型：`int8` / `float16` / `float32` |
| `local_hf_repo_id` | `""` | 自定义 HF 仓库（空则用 `Systran/faster-whisper-{size}`） |
| `hf_endpoint` | `""` | HF 镜像地址 |
| `hf_token` | `""` | HuggingFace 访问 Token |

---

## WebUI API

WebUI 通过以下接口与 TTS/STT 交互（实现在 [`src/webui/app.py`](../../src/webui/app.py)）：

### TTS

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/tts/config` | 读取当前 TTS 配置 |
| POST | `/api/tts/config/save` | 保存 TTS 配置到 YAML |
| POST | `/api/tts/synthesize` | 一次性合成音频，返回下载 URL |
| GET | `/api/tts/download` | 下载已合成的音频文件 |
| WS | `/ws/tts` | 流式 TTS：发送文本，服务端持续推送音频 chunk |

### STT

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/stt/config` | 读取当前 STT 配置 |
| POST | `/api/stt/config/save` | 保存 STT 配置到 YAML |
| POST | `/api/stt/transcribe` | 上传音频文件，返回转录文本 |
| GET | `/api/stt/download` | 下载本地 STT 模型（faster-whisper） |
| WS | `/ws/stt` | 实时 STT：持续发送音频 chunk，返回转录文本 |

### WebSocket 协议示例（`/ws/tts`）

```
Client → Server:  {"text": "你好，世界！"}
Server → Client:  <binary audio chunk> × N
Server → Client:  {"done": true}
```

---

## 依赖安装

默认（仅 Edge TTS）：

```bash
pip install edge-tts
```

本地 STT（faster-whisper）：

```bash
pip install faster-whisper
# 见 requirements-voice-local.txt
```

Kokoro（本地 TTS）：

```bash
pip install kokoro
# 首次使用自动从 HuggingFace 下载模型
```
