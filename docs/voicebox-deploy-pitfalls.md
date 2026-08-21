# Voicebox 部署踩坑记录

> Date: 2026-08-21 | Project: voicebox

---

## 环境概况

- OS: Linux 6.8.0-136-generic (x86_64)
- Python: 3.11.8 (系统自带，无 3.12/3.13)
- Bun: 1.3.11 (`/root/.nvm/versions/node/v22.22.1/bin/bun`)
- Rust: 1.84.1
- GPU: 无 (CPU only)

---

## 坑 1：just 安装失败（rustc 版本不兼容）

**现象**：执行 `just setup-python` 报错 `just: command not found`。

**原因**：`just` 最新版 1.58.0 要求 rustc 1.89.0+，而系统只有 1.84.1。

**尝试过的路（都失败了）**：

```bash
# 方式1: cargo install just (最新)
cargo install just
# 报错: requires rustc 1.89.0 or newer

# 方式2: cargo install just --version 1.46.0
cargo install just --version 1.46.0
# 报错: feature 'edition2024' is required (blake3 依赖问题)

# 方式3: cargo install just --version 1.35.0
# 同样的 blake3 edition2024 报错
```

**解法**：

```bash
# 用官方 install.sh 安装预编译二进制（绕过 rustc 版本限制）
curl -fsSL https://just.systems/install.sh | bash -s -- --to /usr/local/bin
# 成功: just 1.58.0
```

---

## 坑 2：Python 版本只有 3.11

**现象**：justfile 第 38 行有检查 `PY_MINOR > 13` 会报警告；部分 ML 包（chatterbox-tts、hume-tada）要求 Python 3.12。

**实际影响**：不大。setup-python 脚本已用 `--no-deps` 绕过了 chatterbox 和 hume-tada 的 torch 版本限制，3.11 能正常安装全部依赖。

---

## 坑 3：backend/venv 不存在

**现象**：直接跑 `python3 -m uvicorn backend.main:app` 报错 `ModuleNotFoundError: fastapi ...`。

**原因**：依赖未装。系统全局 Python 没有 voicebox 所需的包。

**解法**：跳过大象（just setup），直接用 pip 装核心包后启动：

```bash
# 核心依赖（已安装）
fastapi uvicorn pydantic sqlalchemy alembic

# 启动后端（HF 离线模式）
HF_HUB_OFFLINE=1 python3 -m uvicorn backend.main:app --reload --port 17493
```

---

## 坑 4：GPU 不可用（CPU only）

**现象**：`/health` 返回 `"gpu_available": false`。

**原因**：机器无 NVIDIA/AMD GPU。

**影响**：TTS 推理走 CPU，速度较慢但不报错。Qwen3-TTS 等模型仍可正常加载推理。

---

## 坑 5：MCP 服务器正常但模型未加载

**现象**：`/health` 返回 `"model_loaded": false`。

**原因**：后端启动时没有加载任何 TTS 模型（懒加载，首次请求时才加载）。

**影响**：正常，首次 TTS 请求会自动触发模型加载。

---

## 坑 6：SQLite 数据库路径

**现象**：日志显示 `Database: /opt/voicebox/data/voicebox.db`。

**实际情况**：数据库已存在（4 profiles, 32 generations），无需初始化。

---

## 坑 7：Tauri sidecar 二进制不存在

**现象**：`src-tauri/binaries/` 目录不存在。

**影响**：桌面端 Tauri dev 模式会受影响；纯 API / web 模式不受影响。

**解法**：`just build-server`（需要完整 venv）。

---

## 快速启动命令（跳过 just）

```bash
# 核心依赖（假设已装）
pip install fastapi uvicorn pydantic sqlalchemy alembic huggingface_hub transformers torch accelerate

# 启动（离线优先）
HF_HUB_OFFLINE=1 python3 -m uvicorn backend.main:app --reload --port 17493

# 验证
curl http://127.0.0.1:17493/health
```

---

## git 状态

```
M .gitignore       (修改)
M .mcp.json        (修改)
M CLAUDE.md        (修改)
?? docs/offline-model-cache.md       (新)
?? docs/openmontage-integration.md   (新)
?? scripts/download_models_nightly.sh (新)
?? scripts/verify_model_cache.py     (新)
```

---

## 结论

最小可运行路径：**已有全局 Python + fastapi/uvicorn 已装 + HF 离线** → 直接 `uvicorn backend.main:app` 即可跑起来。GPU 加速和完整 venv 可以后续按需配置。
