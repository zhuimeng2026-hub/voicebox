# Voicebox API 使用指南

Voicebox 是一个本地优先的 AI 语音工作室，通过 REST API 提供文本转语音、语音克隆和语音识别等功能。默认运行在 `http://127.0.0.1:17493`。

## 目录

- [基础信息](#基础信息)
- [快速入门](#快速入门)
- [TTS 语音生成](#tts-语音生成)
- [语音克隆（创建声音档案）](#语音克隆创建声音档案)
- [语音识别（语音转文字）](#语音识别语音转文字)
- [音频播放与下载](#音频播放与下载)
- [后处理音效](#后处理音效)
- [Speak API（简洁入口）](#speak-api简洁入口)
- [MCP 服务（AI 代理集成）](#mcp-服务ai-代理集成)
- [模型管理](#模型管理)
- [录音管理（Captures）](#录音管理captures)
- [音视频通道管理](#音视频通道管理)
- [讲故事编辑器](#讲故事编辑器)
- [系统管理](#系统管理)

---

## 基础信息

| 项目 | 值 |
|------|-----|
| 基础 URL | `http://127.0.0.1:17493` |
| 默认端口 | 17493 |
| 启动方式 | `systemctl start voicebox` |
| 服务状态 | `systemctl status voicebox` |
| 查看日志 | `journalctl -u voicebox -f` |
| Swagger UI | `http://127.0.0.1:17493/docs` |

### systemd 管理

```bash
# 启动
sudo systemctl start voicebox

# 停止
sudo systemctl stop voicebox

# 重启
sudo systemctl restart voicebox

# 查看状态
sudo systemctl status voicebox

# 开机自启
sudo systemctl enable voicebox

# 实时日志
journalctl -u voicebox -f -n 50
```

---

## 快速入门

### 检查服务状态

```bash
curl http://127.0.0.1:17493/health
```

预期响应：

```json
{
  "status": "healthy",
  "model_loaded": false,
  "gpu_available": false,
  "gpu_type": null,
  "backend_type": "pytorch",
  "backend_variant": "cpu"
}
```

### 可用引擎一览

| 引擎 ID | 说明 | 语言 | CPU 表现 |
|---------|------|------|---------|
| `kokoro` | 超轻量预设声音（82M 参数） | en, es, fr, hi, it, pt, ja, zh | ⚡ 极快 |
| `luxtts` | 轻量级声音克隆 | en | ⚡ 150x 实时 |
| `chatterbox_turbo` | 快速英文+表情标签 | en | ✅ 良好 |
| `chatterbox` | 多语言（23 种） | 广泛 | ✅ 可用 |
| `qwen` | Qwen3-TTS 克隆（默认） | 10 种 | 🐢 较慢 |
| `qwen_custom_voice` | Qwen 预设声音 | 10 种 | 🐢 较慢 |
| `tada` | HumeAI 大模型 | 10 种 | 🐢 很慢 |

---

## TTS 语音生成

### 基础生成

需要先创建一个声音档案（见下文），然后使用 `profile_id` 生成语音。

```bash
curl -X POST http://127.0.0.1:17493/generate \
  -H "Content-Type: application/json" \
  -d '{
    "profile_id": "<profile_id>",
    "text": "你好，欢迎使用 Voicebox 语音合成系统。",
    "language": "zh",
    "engine": "kokoro"
  }'
```

参数说明：

| 参数 | 必填 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `profile_id` | ✅ | string | — | 声音档案 ID |
| `text` | ✅ | string | — | 合成文本（1~50000 字） |
| `language` | | string | `"en"` | 语言代码：zh/en/ja/ko/de/fr/ru/pt/es/it 等 |
| `engine` | | string | `"qwen"` | 引擎：qwen / qwen_custom_voice / luxtts / chatterbox / chatterbox_turbo / tada / kokoro |
| `seed` | | int | — | 随机种子（固定可复现结果） |
| `model_size` | | string | `"1.7B"` | 模型大小：仅 qwen 引擎支持 `1.7B` / `0.6B` |
| `instruct` | | string | — | 指令参数（仅 qwen_custom_voice 支持） |
| `personality` | | bool | `false` | 是否通过角色人格 LLM 重写文本后再 TTS |
| `max_chunk_chars` | | int | `800` | 长文本分块字符数（100~5000） |
| `crossfade_ms` | | int | `50` | 分块间交叉淡入淡出毫秒数（0=硬切） |
| `normalize` | | bool | `true` | 是否归一化音频音量 |
| `effects_chain` | | array | null | 后处理音效链 |

响应示例：

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "profile_id": "abc-123",
  "text": "你好，欢迎使用 Voicebox 语音合成系统。",
  "language": "zh",
  "status": "completed",
  "engine": "kokoro",
  "duration": 3.5,
  "created_at": "2026-07-26T05:48:44"
}
```

生成完成后，通过返回的 `id` 获取音频文件：

```bash
curl -o output.wav http://127.0.0.1:17493/audio/<generation_id>
```

### 查询生成状态

```bash
curl http://127.0.0.1:17493/generate/<generation_id>/status
```

返回状态：`queued` → `loading_model` → `generating` → `completed` / `failed`

### 流式生成（直接返回 WAV 字节流）

适用于不需要保存历史记录的实时场景：

```bash
curl -X POST http://127.0.0.1:17493/generate/stream \
  -H "Content-Type: application/json" \
  -d '{
    "profile_id": "<profile_id>",
    "text": "This is streaming audio generation.",
    "engine": "kokoro"
  }' -o stream_output.wav
```

### 重试失败/重新生成

```bash
# 重试（保留种子）
curl -X POST http://127.0.0.1:17493/generate/<generation_id>/retry

# 重新生成（新随机种子，创建新版本）
curl -X POST http://127.0.0.1:17493/generate/<generation_id>/regenerate

# 取消进行中的生成
curl -X POST http://127.0.0.1:17493/generate/<generation_id>/cancel
```

### 查看版本列表

每次重生成或应用音效后都会创建"版本"：

```bash
curl http://127.0.0.1:17493/generations/<generation_id>/versions
```

---

## 语音克隆（创建声音档案）

### 列出已有声音档案

```bash
curl http://127.0.0.1:17493/profiles
```

### 创建声音档案（克隆型）

克隆型需要先上传参考音频样本。

**第一步：创建档案**

```bash
curl -X POST http://127.0.0.1:17493/profiles \
  -H "Content-Type: application/json" \
  -d '{
    "name": "我的声音",
    "language": "zh",
    "voice_type": "cloned",
    "default_engine": "kokoro"
  }'
```

| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `name` | ✅ | string | 声音名称（1~100 字符） |
| `description` | | string | 描述（~500 字符） |
| `language` | | string | 语言代码（默认 "en"） |
| `voice_type` | | string | 类型：`cloned`（克隆）/ `preset`（预设）/ `designed`（文本描述） |
| `preset_engine` | | string | 预设声音的引擎（仅 `preset` 类型） |
| `preset_voice_id` | | string | 预设声音 ID（仅 `preset` 类型） |
| `design_prompt` | | string | 文本描述声音（仅 `designed` 类型） |
| `default_engine` | | string | 默认使用的 TTS 引擎 |
| `personality` | | string | 角色人格描述（~2000 字符），用于 `Compose` 和 `Speak in character` 功能 |

**第二步：上传参考音频样本**

```bash
curl -X POST http://127.0.0.1:17493/profiles/<profile_id>/samples \
  -F "audio=@/path/to/sample.wav" \
  -F "reference_text=这是参考录音的原文内容"
```

> 参考音频建议 5~30 秒，清晰无背景噪音，与目标语言一致。

### 预设型声音档案（Kokoro 50+ 预设声音）

无需上传样本，直接使用内置预设：

```bash
# 查看指定引擎的所有预设声音
curl http://127.0.0.1:17493/profiles/presets/kokoro

# 创建预设声音档案
curl -X POST http://127.0.0.1:17493/profiles \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Kokoro Adam",
    "voice_type": "preset",
    "preset_engine": "kokoro",
    "preset_voice_id": "am_adam"
  }'
```

### 更新和删除

```bash
# 更新档案
curl -X PUT http://127.0.0.1:17493/profiles/<profile_id> \
  -H "Content-Type: application/json" \
  -d '{"name": "新名字", "personality": "性格描述"}'

# 删除档案
curl -X DELETE http://127.0.0.1:17493/profiles/<profile_id>

# 导出档案
curl http://127.0.0.1:17493/profiles/<profile_id>/export > profile.json
```

---

## 语音识别（语音转文字）

使用 Whisper 模型将音频转为文字：

```bash
curl -X POST http://127.0.0.1:17493/transcribe \
  -F "audio=@/path/to/recording.wav" \
  -F "model=turbo" \
  -F "language=en"
```

| 参数 | 必填 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `audio` | ✅ | file | — | WAV/MP3 音频文件 |
| `model` | | string | `"turbo"` | Whisper 模型：base / small / medium / large / turbo |
| `language` | | string | auto | 语言代码（留空则自动检测） |

响应：

```json
{
  "text": "这是识别出的文字内容",
  "duration": 5.2
}
```

---

## 音频播放与下载

```bash
# 获取生成音频（WAV）
curl -o output.wav http://127.0.0.1:17493/audio/<generation_id>

# 获取特定版本的音频
curl -o version.wav http://127.0.0.1:17493/audio/version/<version_id>

# 获取录音文件
curl -o capture.wav http://127.0.0.1:17493/captures/<capture_id>/audio

# 导出生成记录（含元数据 JSON + 音频路径）
curl http://127.0.0.1:17493/history/<generation_id>/export

# 直接下载生成音频文件
curl -o audio.wav http://127.0.0.1:17493/history/<generation_id>/export-audio
```

---

## 后处理音效

### 查看可用的音效

```bash
curl http://127.0.0.1:17493/effects/available
```

### 音效预设

```bash
# 查看音效预设列表
curl http://127.0.0.1:17493/effects/presets

# 创建音效预设
curl -X POST http://127.0.0.1:17493/effects/presets \
  -H "Content-Type: application/json" \
  -d '{
    "name": "混响大厅",
    "description": "大厅混响效果",
    "effects_chain": [
      {"type": "reverb", "enabled": true, "params": {"room_size": 0.8, "damping": 0.5, "wet_level": 0.3, "dry_level": 0.7}}
    ]
  }'
```

### 生成时应用音效

```bash
curl -X POST http://127.0.0.1:17493/generate \
  -H "Content-Type: application/json" \
  -d '{
    "profile_id": "<profile_id>",
    "text": "Hello with reverb!",
    "engine": "kokoro",
    "effects_chain": [
      {"type": "reverb", "enabled": true, "params": {"room_size": 0.8, "damping": 0.5, "wet_level": 0.3, "dry_level": 0.7}}
    ]
  }'
```

支持的音效类型：`reverb`, `delay`, `chorus`, `pitch_shift`, `compressor`, `low_pass`, `high_pass`, `distortion`

### 对已有生成应用音效

```bash
curl -X POST http://127.0.0.1:17493/generations/<generation_id>/versions/apply-effects \
  -H "Content-Type: application/json" \
  -d '{
    "effects_chain": [
      {"type": "pitch_shift", "enabled": true, "params": {"semitones": 2}}
    ]
  }'
```

### 试听效果（不保存）

```bash
curl -X POST http://127.0.0.1:17493/effects/preview/<generation_id> \
  -H "Content-Type: application/json" \
  -d '{
    "effects_chain": [{"type": "reverb", "enabled": true, "params": {"room_size": 0.5}}]
  }' -o preview.wav
```

---

## Speak API（简洁入口）

一个专为脚本和自动化设计的轻量入口，支持按名称模糊匹配声音档案：

```bash
curl -X POST http://127.0.0.1:17493/speak \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello, this is a test message.",
    "profile": "我的声音",
    "engine": "kokoro",
    "personality": false,
    "language": "en"
  }'
```

| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `text` | ✅ | string | 要朗读的文本 |
| `profile` | | string | 声音名称或 ID（不区分大小写）。不传时使用客户端绑定或全局默认 |
| `engine` | | string | 引擎，默认使用 profile 的 default_engine |
| `personality` | | bool | 是否启用角色人格重写（需 profile 设置了 personality） |
| `language` | | string | 语言代码 |

> 与 `/generate` 不同的是，`profile` 参数可以使用声音档案的名称（case-insensitive），而无需先查询 ID。

---

## MCP 服务（AI 代理集成）

Voicebox 内置 Model Context Protocol（MCP）服务器，让 AI 代理可以直接调用语音能力。

### 端点

MCP 服务挂载在 `http://127.0.0.1:17493/mcp`，使用 Streamable HTTP 传输协议。

### 客户端绑定管理

在 Settings → MCP 中可以为每个 AI 客户端绑定不同的声音：

```bash
# 查看所有绑定
curl http://127.0.0.1:17493/mcp/bindings

# 创建/更新绑定
curl -X PUT http://127.0.0.1:17493/mcp/bindings \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "claude-code",
    "label": "Claude Code",
    "profile_id": "<profile_id>",
    "default_engine": "kokoro",
    "default_personality": false
  }'

# 删除绑定
curl -X DELETE http://127.0.0.1:17493/mcp/bindings/claude-code
```

### Claude Code 连接

```bash
# 添加 MCP 服务
claude mcp add voicebox \
  --transport http \
  --url http://127.0.0.1:17493/mcp \
  --header "X-Voicebox-Client-Id: claude-code"
```

### 其他 MCP 客户端（Cursor / VS Code 等）

在 `~/.cursor/mcp.json` 或 `.vscode/mcp.json` 中配置：

```json
{
  "mcpServers": {
    "voicebox": {
      "url": "http://127.0.0.1:17493/mcp",
      "headers": { "X-Voicebox-Client-Id": "cursor" }
    }
  }
}
```

### MCP 工具列表

| 工具 | 说明 |
|------|------|
| `voicebox.speak` | 在声音档案中朗读文本 |
| `voicebox.transcribe` | 将音频转为文字 |
| `voicebox.list_captures` | 查看最近的录音列表 |
| `voicebox.list_profiles` | 列出所有声音档案 |

### SSE 事件

监听实时说话状态：

```bash
curl -N http://127.0.0.1:17493/events/speak
```

---

## 模型管理

Voicebox 的模型在首次使用时自动从 HuggingFace 下载到缓存目录。

```bash
# 查看所有模型状态
curl http://127.0.0.1:17493/models/status

# 下载指定模型
curl -X POST http://127.0.0.1:17493/models/download \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "kokoro"
  }'

# 取消下载
curl -X POST http://127.0.0.1:17493/models/download/cancel

# 查看下载进度
curl http://127.0.0.1:17493/models/progress/kokoro

# 加载模型到内存
curl -X POST http://127.0.0.1:17493/models/load \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "kokoro"
  }'

# 卸载模型释放内存
curl -X POST http://127.0.0.1:17493/models/unload \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "kokoro"
  }'

# 删除模型文件
curl -X DELETE http://127.0.0.1:17493/models/kokoro

# 查看模型缓存目录
curl http://127.0.0.1:17493/models/cache-dir
```

模型名称参考：`kokoro`, `luxtts`, `qwen-tts-1.7B`, `qwen-tts-0.6B`, `qwen-custom-voice-1.7B`, `chatterbox-tts`, `chatterbox-turbo`, `tada-1b`, `tada-3b-ml`, `whisper-turbo`, `whisper-base`, `qwen3-0.6b` 等。

---

## 录音管理（Captures）

Captures 管理语音输入记录（听写、录音、上传文件）。

```bash
# 列出录音
curl http://127.0.0.1:17493/captures

# 查询单个录音
curl http://127.0.0.1:17493/captures/<capture_id>

# 删除录音
curl -X DELETE http://127.0.0.1:17493/captures/<capture_id>

# 重新转写（更换模型）
curl -X POST http://127.0.0.1:17493/captures/<capture_id>/retranscribe \
  -H "Content-Type: application/json" \
  -d '{"model": "turbo", "language": "en"}'

# 智能润色（通过 LLM 优化转写文本）
curl -X POST http://127.0.0.1:17493/captures/<capture_id>/refine \
  -H "Content-Type: application/json" \
  -d '{
    "flags": {
      "smart_cleanup": true,
      "self_correction": true,
      "preserve_technical": true
    }
  }'

# 上传录音
curl -X POST http://127.0.0.1:17493/captures \
  -F "audio=@/path/to/recording.wav" \
  -F "source=file" \
  -F "language=en"

# 检查听写功能可用性
curl http://127.0.0.1:17493/capture/readiness
```

### 听写设置

```bash
# 查看当前设置
curl http://127.0.0.1:17493/settings/captures

# 更新设置
curl -X PUT http://127.0.0.1:17493/settings/captures \
  -H "Content-Type: application/json" \
  -d '{
    "stt_model": "turbo",
    "language": "auto",
    "auto_refine": true,
    "llm_model": "0.6B",
    "smart_cleanup": true,
    "self_correction": true,
    "preserve_technical": true,
    "allow_auto_paste": true,
    "hotkey_enabled": false
  }'
```

---

## 音视频通道管理

音频输出通道管理（选择哪个设备播放声音）。

```bash
# 列出所有通道
curl http://127.0.0.1:17493/channels

# 创建新通道
curl -X POST http://127.0.0.1:17493/channels \
  -H "Content-Type: application/json" \
  -d '{
    "name": "扬声器",
    "device_ids": ["default"]
  }'

# 更新通道
curl -X PUT http://127.0.0.1:17493/channels/<channel_id> \
  -H "Content-Type: application/json" \
  -d '{"name": "耳机", "device_ids": ["headset-output"]}'

# 删除通道
curl -X DELETE http://127.0.0.1:17493/channels/<channel_id>

# 查看通道绑定的声音档案
curl http://127.0.0.1:17493/channels/<channel_id>/voices

# 设置通道绑定哪些声音
curl -X PUT http://127.0.0.1:17493/channels/<channel_id>/voices \
  -H "Content-Type: application/json" \
  -d '{"profile_ids": ["<profile_id1>", "<profile_id2>"]}'

# 查看声音档案绑定的通道
curl http://127.0.0.1:17493/profiles/<profile_id>/channels

# 设置声音档案的通道
curl -X PUT http://127.0.0.1:17493/profiles/<profile_id>/channels \
  -H "Content-Type: application/json" \
  -d '{"channel_ids": ["<channel_id>"]}'
```

---

## 讲故事编辑器

多轨时间线编辑器，适合对话、播客和叙事场景。

```bash
# 创建故事
curl -X POST http://127.0.0.1:17493/stories \
  -H "Content-Type: application/json" \
  -d '{"name": "双人对话", "description": "Interview podcast"}'

# 列出故事
curl http://127.0.0.1:17493/stories

# 获取故事详情
curl http://127.0.0.1:17493/stories/<story_id>

# 更新故事
curl -X PUT http://127.0.0.1:17493/stories/<story_id> \
  -H "Content-Type: application/json" \
  -d '{"name": "new name"}'

# 删除故事
curl -X DELETE http://127.0.0.1:17493/stories/<story_id>

# 添加时间线条目（关联生成的语音）
curl -X POST http://127.0.0.1:17493/stories/<story_id>/items \
  -H "Content-Type: application/json" \
  -d '{
    "generation_id": "<generation_id>",
    "version_id": "<version_id>",
    "start_time_ms": 0,
    "track": 0,
    "volume": 1.0
  }'

# 故事导出为完整音频
curl -o story.wav http://127.0.0.1:17493/stories/<story_id>/export-audio
```

---

## 系统管理

### 服务健康检查

```bash
# 基本健康
curl http://127.0.0.1:17493/health

# 文件系统健康
curl http://127.0.0.1:17493/health/filesystem
```

### 查看生成历史

```bash
# 历史列表（带分页）
curl "http://127.0.0.1:17493/history?limit=20&offset=0"

# 按声音筛选
curl "http://127.0.0.1:17493/history?profile_id=<profile_id>"

# 搜索文本
curl "http://127.0.0.1:17493/history?search=关键字"

# 统计
curl http://127.0.0.1:17493/history/stats

# 删除单条记录
curl -X DELETE http://127.0.0.1:17493/history/<generation_id>

# 清空失败记录
curl -X DELETE http://127.0.0.1:17493/history/failed

# 收藏/取消收藏
curl -X POST http://127.0.0.1:17493/history/<generation_id>/favorite \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 缓存管理

```bash
# 清理缓存
curl -X POST http://127.0.0.1:17493/cache/clear
```

### 生成设置

```bash
# 查看生成设置
curl http://127.0.0.1:17493/settings/generation

# 更新生成设置
curl -X PUT http://127.0.0.1:17493/settings/generation \
  -H "Content-Type: application/json" \
  -d '{
    "max_chunk_chars": 800,
    "crossfade_ms": 50,
    "normalize_audio": true,
    "autoplay_on_generate": true
  }'
```

### CUDA / ROCm 后端

```bash
# CUDA 状态
curl http://127.0.0.1:17493/backend/cuda-status

# 下载 CUDA 后端
curl -X POST http://127.0.0.1:17493/backend/download-cuda

# 下载 ROCm 后端
curl -X POST http://127.0.0.1:17493/backend/download-rocm
```

### 主动关闭服务

```bash
# 优雅关闭
curl -X POST http://127.0.0.1:17493/shutdown
```

### 任务管理

```bash
# 查看活跃任务
curl http://127.0.0.1:17493/tasks/active

# 清除已完成任务
curl -X POST http://127.0.0.1:17493/tasks/clear
```

---

## 完整示例：从零开始生成语音

```bash
#!/bin/bash

BASE="http://127.0.0.1:17493"

# 1. 创建声音档案
echo "=== 创建声音档案 ==="
PROFILE=$(curl -s -X POST "$BASE/profiles" \
  -H "Content-Type: application/json" \
  -d '{"name": "测试声音", "language": "zh", "default_engine": "kokoro"}')
PROFILE_ID=$(echo $PROFILE | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Profile ID: $PROFILE_ID"

# 2. 对于预设类型，可以跳过样本上传直接使用
#    对于克隆类型，需要上传参考音频
if [ -f "sample.wav" ]; then
  curl -X POST "$BASE/profiles/$PROFILE_ID/samples" \
    -F "audio=@sample.wav" \
    -F "reference_text=这是参考录音的文字"
fi

# 3. 生成语音
echo "=== 生成语音 ==="
GEN=$(curl -s -X POST "$BASE/generate" \
  -H "Content-Type: application/json" \
  -d "{
    \"profile_id\": \"$PROFILE_ID\",
    \"text\": \"你好，这是一个测试语音。\",
    \"language\": \"zh\",
    \"engine\": \"kokoro\",
    \"normalize\": true
  }")
GEN_ID=$(echo $GEN | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Generation ID: $GEN_ID"

# 4. 等待完成并下载
sleep 2
curl -o output.wav "$BASE/audio/$GEN_ID"
echo "已下载到 output.wav"

# 5. 或者使用 Speak API（更简洁）
curl -X POST "$BASE/speak" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "直接用名字调用，无需查 ID",
    "profile": "测试声音",
    "engine": "kokoro",
    "language": "zh"
  }'
```

---

## 故障排除

### 服务无法启动

```bash
journalctl -u voicebox -n 50 --no-pager
```

常见原因：
- **端口被占用**：`lsof -i :17493` 检查端口
- **Python 依赖缺失**：在 `/opt/voicebox` 目录下运行 `pip3 install -r backend/requirements.txt`
- **数据库损坏**：删除 `/opt/voicebox/data/voicebox.db` 后重启（会重建）

### 生成失败

- **模型未下载**：首次使用会自动下载模型，需联网。也可通过 `POST /models/download` 预先下载
- **引擎不支持当前语言**：请参考上方引擎表选择正确引擎
- **CPU 内存不足**：大模型（qwen 1.7B / tada-1b）需要较多内存，优先使用 kokoro 或 luxtts

### 调试模式

```bash
# 直接运行查看详细日志
sudo systemctl stop voicebox
cd /opt/voicebox && python3 -m backend.main --host 127.0.0.1 --port 17493
```
