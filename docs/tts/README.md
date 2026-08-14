# TTS / STT

`src/tts/` 是独立的语音适配层。配置类位于 `src/config/tts/`，运行配置文件是 `config/tts/tts.yaml` 与 `config/tts/stt.yaml`。

## Engine 与 provider

`TTSEngine.from_config()` 支持：

- `edge` → `EdgeTTSProvider`
- `openai` → `OpenAITTSProvider`
- `kokoro` → `KokoroProvider`

接口为异步 `stream(text) -> AsyncIterator[bytes]` 和 `synthesize(text) -> bytes`。

`STTEngine.from_config()` 支持：

- `openai` → `OpenAISTTProvider`
- `faster_whisper` → `FasterWhisperProvider`

接口为异步 `transcribe(audio: bytes, mime_type="audio/webm") -> str`。未知 provider 直接抛出 `ValueError`。

也可通过 `TTSEngine.from_yaml(path)` 与 `STTEngine.from_yaml(path)` 创建。WebUI 则在第一次语音请求时懒创建 engine；保存配置后把对应缓存设为 `None`，下一次请求重新装配。

## 配置

`TTSConfig` 当前字段：

- 通用：`provider`、`voice`、`rate`、`volume`、`output_format`
- OpenAI：`openai_model`、`openai_base_url`、`openai_api_key`
- Kokoro：`kokoro_model_path`、`kokoro_device`、`kokoro_hf_repo_id`
- HuggingFace：`hf_endpoint`、`hf_token`

默认 provider 是 `edge`，默认 voice 是 `zh-CN-XiaoxiaoNeural`。

`STTConfig` 当前字段：

- 通用：`provider`、`language`、`output_format`
- OpenAI：`openai_model`、`openai_base_url`、`openai_api_key`
- faster-whisper：`local_model_size`、`local_model_path`、`local_device`、`local_compute_type`、`local_hf_repo_id`
- HuggingFace：`hf_endpoint`、`hf_token`

默认 provider 是 `openai`，默认模型是 `whisper-1`。

## WebUI API

API 实现在 `src/webui/routers/voice.py`。

TTS：

- `GET /api/tts/config`
- `POST /api/tts/config/save`
- `POST /api/tts/synthesize`：响应体直接是 `audio/mpeg` 字节，不返回下载 URL。
- `WS /ws/tts`：客户端先发 `{"text": "..."}`，服务端发送二进制 chunk，完成后直接关闭 socket。
- `GET /api/tts/download`：下载 Kokoro 模型到 `models/kokoro/{repo-id}`，通过 SSE 返回进度；它不是合成音频下载接口。

STT：

- `GET /api/stt/config`
- `POST /api/stt/config/save`
- `POST /api/stt/transcribe`
- `WS /ws/stt`：服务端先缓存客户端发送的所有音频 chunk，收到文本帧 `{"done": true, "mime_type": "..."}` 后一次性转录并返回结果；不是增量实时识别。
- `GET /api/stt/download`：下载模型到 `models/whisper/{repo-id}`，通过 SSE 返回进度。

## 与 Speak、workspace 的边界

Soul Speak 的入口是 `src/webui/routers/speak.py` 中的 `WS /ws/speak/run`。它负责文本会话、Soul 编排和文本流事件，不调用 `TTSEngine` 或 `STTEngine`。需要语音交互的客户端应自行串联：

```text
音频 → /api/stt/transcribe 或 /ws/stt → 文本
文本 → /ws/speak/run → 回复文本
回复文本 → /api/tts/synthesize 或 /ws/tts → 音频
```

`.react/workspace` 是 `SandboxManager` 的文件工具沙箱，不是 Speak 会话目录，也不是语音缓存目录。TTS 的 REST/WS 路径直接返回音频字节；faster-whisper 仅创建操作系统临时 `.wav` 并在转录后删除。显式模型下载写入项目根目录下的 `models/kokoro/` 或 `models/whisper/`，不写入 `.react/workspace`。
