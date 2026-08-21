# Offline Model Cache: 校验与打包（Qwen3-TTS-12Hz 离线部署）

> Date: 2026-08-21 | Status: Operational Guide

## 背景与场景

Voicebox 的 Qwen3-TTS 模型部署到**出网受限**的机器上时,需要先在联网机器上下全模型,再整体搬过去,之后以 `HF_HUB_OFFLINE=1` 离线运行。本文档回答两类问题:

1. **怎么判断某模型在 HF cache 里是否真的下全了**(避免把"路径误解"当成"下载不完整")。
2. **怎么正确地把 cache 搬到另一台机器**(传输方式错了会导致"blob 缺失"的误判)。

适用模型: `Qwen/Qwen3-TTS-12Hz-1.7B-Base`(及其 0.6B / CustomVoice / mlx 变体)、Kokoro、Whisper 等一切走 `huggingface_hub` cache 的模型。

---

## 1. HF cache 目录结构(关键前提)

HuggingFace Hub 的磁盘布局是**双层**的:

```
~/.cache/huggingface/hub/models--Qwen--Qwen3-TTS-12Hz-1.7B-Base/
├── blobs/                      # ← 真正的实体文件(权重全在这里)
│   ├── 836b7b357f5e...         # speech_tokenizer/model.safetensors (682 MB)
│   └── 38fc7fc51c5e...         # model.safetensors (3.86 GB)
├── refs/main                   # 分支 → 当前 commit
└── snapshots/<commit-sha>/     # ← 全是软链,指向 blobs/
    ├── model.safetensors -> ../../blobs/38fc7fc5...
    ├── speech_tokenizer/
    │   └── model.safetensors -> ../../../blobs/836b7b35...
    └── config.json -> ../../blobs/81b57e8e...
```

**最常见的误判**: `ls snapshot/` 里只看到一串指向 `../../blobs/xxx` 的软链,有人就以为"实体文件不存在 / 下载不完整"。其实 `blobs/` 本来就不在 `snapshots/` 里面,而在它的上一级。判断完整性**必须解析软链**,不能只 `ls snapshot`。

同理,若把 cache 搬到别的机器时**只拷贝了 `snapshots/`(或拷贝时没解引用软链)**,软链到了目标机就会全部悬空 → 这才是真正的"blob 缺失"。详见第 4 节。

---

## 2. Qwen3-TTS-12Hz-1.7B-Base"下全"长什么样

该仓库整仓 **4.54 GB**,由两部分组成,**缺一不可**:

| 文件 | 大小 | 作用 |
|---|---|---|
| `model.safetensors`(顶层) | 3.86 GB | TTS 主模型权重(`Qwen3TTSForConditionalGeneration`,1.7B talker LM) |
| `speech_tokenizer/model.safetensors` | 682 MB | 语音编解码器(12Hz codec encoder/decoder) |
| `speech_tokenizer/config.json` | 2.3 kB | codec 配置(`qwen3_tts_tokenizer_12hz`) |
| `speech_tokenizer/preprocessor_config.json` 等 | ~0.3 kB | codec 预处理配置 |
| `config.json` / `tokenizer_config.json` / `generation_config.json` / `preprocessor_config.json` | ~12 kB | 主模型配置 |
| `vocab.json` / `merges.txt` / `README.md` / `.gitattributes` | ~4.5 MB | tokenizer 词表等 |

**重要结论**:

- **speech_tokenizer 是主仓库内的一个子目录,不是独立子仓库。** voicebox 后端的 `qwen_tts` 包(`qwen_tts/core/models/modeling_qwen3_tts.py`)通过 `cached_file(repo, "speech_tokenizer/config.json")` 从**同一个主仓库**里解析它,随后 `Qwen3TTSTokenizer.from_pretrained(...)` 加载。所以 `huggingface-cli download Qwen/Qwen3-TTS-12Hz-1.7B-Base` 全量下载即自带 tokenizer。
- 独立仓库 `Qwen/Qwen3-TTS-Tokenizer-12Hz`(682 MB)README 里有列,但 **voicebox 后端代码不引用它**,普通部署不用下。
- 缺了 `speech_tokenizer/`(或只下顶层 `model.safetensors`)时,加载会在 `cached_file("speech_tokenizer/config.json")` 处失败——这是"服务反复联网"的典型原因之一。

下载(联网机器上):

```bash
huggingface-cli download Qwen/Qwen3-TTS-12Hz-1.7B-Base
# 不要加 --include/--exclude 过滤,保持全量
```

---

## 3. 正确校验一个模型是否完整

对任意 HF cache 仓库,跑下面三步;**无输出 = 完整**。

```bash
REPO=~/.cache/huggingface/hub/models--Qwen--Qwen3-TTS-12Hz-1.7B-Base

# ① blobs 实体目录必须存在(真正的权重都在这里)
ls -la "$REPO/blobs/" | head

# ② 软链能解析到实体、且实体大小正确
#    speech_tokenizer 主权重应为 682293092 字节
readlink -f "$REPO"/snapshots/*/speech_tokenizer/model.safetensors
stat -c %s "$(readlink -f "$REPO"/snapshots/*/speech_tokenizer/model.safetensors)"

# ③ 全 repo 有无悬空软链(应无输出)
find "$REPO" -xtype l
```

判定标准:**`blobs/` 存在 + 软链 `readlink -f` 能落到实体 + `find -xtype l` 无输出** → 模型完整可用。

补充:blob 文件名就是该文件的 SHA-256,可交叉校验:

```bash
BLOB=$(readlink -f "$REPO"/snapshots/*/speech_tokenizer/model.safetensors)
[ "$(sha256sum "$BLOB" | cut -d' ' -f1)" = "$(basename "$BLOB")" ] && echo "哈希一致"
```

---

## 4. 决定性验证:直接加载并编解码

检查"文件在不在"是静态校验;最有力的证据是**用后端同一条路径真正加载并跑一遍**。以下脚本以 `HF_HUB_OFFLINE=1` 加载 speech_tokenizer,编码 1 秒音频再解码,输出 `OK` 即为真可用。

```bash
cd /tmp && cat > check_st.py <<'PY'
import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
import glob, numpy as np
from qwen_tts.inference.qwen3_tts_tokenizer import Qwen3TTSTokenizer

path = sorted(glob.glob(os.path.expanduser(
    "~/.cache/huggingface/hub/models--Qwen--Qwen3-TTS-12Hz-1.7B-Base/snapshots/*/speech_tokenizer")))[-1]
tok = Qwen3TTSTokenizer.from_pretrained(path)
print("LOADED:", type(tok.model).__name__)

sr = 24000
wav = (0.1*np.sin(2*np.pi*440*np.linspace(0,1,sr,endpoint=False))).astype(np.float32)
enc = tok.encode(wav, sr=sr)
codes = enc.audio_codes[0]
dec, out_sr = tok.decode(enc)
rms = float(np.sqrt(np.mean(dec[0]**2)))
print(f"codes={tuple(codes.shape)} sr={out_sr} rms={rms:.4f}")
print("OK" if (rms > 1e-3 and out_sr == 24000) else "FAIL")
PY
python check_st.py
```

正常输出形如:

```
LOADED: Qwen3TTSTokenizerV2Model
codes=(13, 16) sr=24000 rms=0.0735
OK
```

(日志里的 `sox: command not found` 可忽略,feature extractor 会自动回退 numpy。)

对**整机可用性**更强的验证:直接跑 `just dev-backend`,在 `/docs`(Swagger)里对 `POST /tts/generate` 发一次真实合成;能出音频就是主模型 + tokenizer 都通。

---

## 5. 打包与传输(导致"blob 缺失"的重灾区)

**原因**:只拷了 `snapshots/`,或 `tar`/`scp` 没解引用软链,导致目标机上软链全部悬空,于是报"blob 文件不存在"。

正确做法二选一:

```bash
# 方式 A:整目录原样搬(blobs + snapshots + refs 一起)
cp -a ~/.cache/huggingface/hub/models--Qwen--Qwen3-TTS-12Hz-1.7B-Base \
      <目标机>/.../models--Qwen--Qwen3-TTS-12Hz-1.7B-Base

# 方式 B:tar 打包时解引用软链(-h),拷成实体文件
tar -chf qwen3-tts.tar -C ~/.cache/huggingface/hub \
      models--Qwen--Qwen3-TTS-12Hz-1.7B-Base
# 目标机解包:
tar -xf qwen3-tts.tar -C ~/.cache/huggingface/hub
```

**绝对不要只拷 `snapshots/` 目录。** 拷完在目标机上跑第 3 节的 `find ... -xtype l`,应为空。

---

## 6. 目标机离线运行配置

```bash
# ① 有自定义模型目录就指它(VOICEBOX_MODELS_DIR 即 HF_HUB_CACHE,见 backend/config.py)
export VOICEBOX_MODELS_DIR=/path/to/cache_dir        # 含 models--Qwen--... 这一层

# ② 强制离线(justfile 的 dev-backend 已默认带 HF_HUB_OFFLINE=1)
export HF_HUB_OFFLINE=1

# ③ 启动
just dev-backend
```

`VOICEBOX_MODELS_DIR` 与默认 `~/.cache/huggingface/hub` 二选一,把第 5 节的仓库目录放进所选位置即可。

---

## 7. 自动化下载 + 续传 + 验证管线

当目标机器出网受限、模型又大(whisper ~1.6 GB + 人格 LLM ~1.3 GB)时,把下载交给脚本,支持断点续传和事后验证,避免手工漏做。两个脚本:

- `scripts/download_models_nightly.sh` — 下载器(可走系统 cron)
- `scripts/verify_model_cache.py` — 离线可用性验证器(`whisper` / `llm` 两个子命令)

### 7.1 下载器状态机(三态,杜绝重复下载)

对每个模型 `download()` 先判定当前缓存状态:

| 状态 | 判定 | 行为 |
|---|---|---|
| 已完整 | 仓库目录存在 + 无悬空软链 + 无 `.incomplete` + snapshot 里 `*.safetensors` 软链能解析到实体 | `skip (already complete)`,不碰 |
| 部分 / 已中断 | 有已完成 blob 或 `.incomplete` | `resume (completed=N, incomplete=M)`,交给 HF CLI 断点续传 |
| 全新 | 无任何缓存 | `download (fresh)` |

**续传 / 去重原理**:HF CLI 把中断的下载写成 `<blob>.incomplete`,重跑时按 HTTP Range 续传;已完成的 blob 按内容 SHA 去重,永不重下。所以中断多少次都可以直接重跑。

> ⚠️ **坑:仓库目录名是双横线。** HF 目录是 `models--openai--whisper-large-v3-turbo`。用 `tr '/' '--'` 生成会得到单横线 `models--openai-whisper-...`(tr 会把 `--` 折叠成集合 `-`),状态判断永远找不到目录。必须用 `sed 's|/|--|g'`。

### 7.2 验证器(下完即验,防"看起来下全其实坏")

`verify_model_cache.py` 严格离线(`HF_HUB_OFFLINE=1`),照后端实际加载路径做**一次真实推理**:

- `whisper`:`WhisperProcessor` + `WhisperForConditionalGeneration` 加载 `openai/whisper-large-v3-turbo`,对 1 s / 16 kHz 音频 `generate`。
- `llm`:`AutoModelForCausalLM` + `AutoTokenizer` 加载 `Qwen/Qwen3-0.6B`,生成 8 个 token。

任一失败 exit 1;两个模型各跑独立进程、顺序执行,用完即释放内存(峰值约 2~3 GB)。手动跑:

```bash
/root/.pyenv/versions/3.11.8/bin/python scripts/verify_model_cache.py whisper
/root/.pyenv/versions/3.11.8/bin/python scripts/verify_model_cache.py llm
```

### 7.3 cron 接线 + 步骤状态日志(一次性,无自清理)

```cron
# 8/22 02:00 触发一次(日期钉死的 cron,只跑当天;脚本不自删、不每晚跑)
0 2 22 8 * /bin/bash /opt/voicebox/scripts/download_models_nightly.sh >> /var/log/hf-model-download.log 2>&1
```

- 系统 cron,终端关掉照跑。**一次性**:用日期钉死(`22 8` = 8 月 22 日),触发一次即止;脚本不做任何 crontab 自清理。
- 若这次失败,不会自动重跑——`cat /var/log/hf-model-download.state` 看停在哪一步,修好后手动重跑即可(脚本幂等 + 续传):`/bin/bash /opt/voicebox/scripts/download_models_nightly.sh`
- **步骤状态文件 `/var/log/hf-model-download.state`**,记录最后一个完成的里程碑(0~6):

  | 步 | 含义 |
  |---|---|
  | 1 | 主模型完整 + SHA 校验 |
  | 2 | whisper 下载完成 |
  | 3 | LLM(Qwen3-0.6B)下载完成 |
  | 4 | MOSS 栈下载完成(TTS-Nano + Audio-Tokenizer-Nano) |
  | 5 | whisper 验证通过 |
  | 6 | LLM 验证通过 |
  | 7 | 全部 done |

  > MOSS 栈 = `OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX`(673 MB,LM + 文本 tokenizer)+ 配套 codec `OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX`(90.6 MB,波形编解码)。**两个都必须下**:TTS 仓库不自包含,没有 codec 合不出声音(官方 README 的下载命令就是两个仓库一起)。Apache-2.0,ONNX 模型(onnxruntime 用,非 transformers 引擎),只做下载 + 完整性检查,**不跑推理验证**。缓存目录名注意是 `models--OpenMOSS-Team--...`(组织名带 `-Team`)。

  每完成一步即写入;异常/被 kill 时,从状态文件和日志能**精确看出停在哪一步**:

  ```
  log "=== FAILED, completed through step 2 (whisper download), stopped before llm download ==="
  ```

- **断点续跑,不从头开始**:
  - 下载按 blob 级续传(已完成的不重下、`.incomplete` 断点续传);
  - 验证若某模型**上一轮已通过且本轮未重下**则跳过(`prev >= 该步` 且未 dirty),只有重下过的模型才重验。
- 日志:`/var/log/hf-model-download.log`(含 `state=N` 步进标记)。中途看:`tail -f /var/log/hf-model-download.log`。

手动重跑(幂等,可随时执行):`/bin/bash /opt/voicebox/scripts/download_models_nightly.sh`

---

## 8. 常见排查速查表

| 现象 | 原因 | 处理 |
|---|---|---|
| 报 `{repo}/None not exists` | 主仓库缺 `speech_tokenizer/` 子目录 | 全量重下 `Qwen/Qwen3-TTS-12Hz-1.7B-Base` |
| 目标机 `find -xtype l` 有输出 | 传输时只拷了 snapshot / 没解引用软链 | 用第 5 节的 `cp -a` 或 `tar -chf` 重传 |
| `ls snapshot` 全是 `../../blobs/...` | 这是正常软链,**不是**缺失 | 用第 3 节 `readlink -f` + `find -xtype l` 判定 |
| 服务反复联网、卡在下载 | 模型未下全 + 未设 `HF_HUB_OFFLINE=1` | 下全 + 设 `HF_HUB_OFFLINE=1` |
| 下载被中断、只下了一部分 | 正常,`.incomplete` 留存 | 直接重跑脚本/CLI,自动续传 |
| 报 `models--openai-whisper-...` 找不到 | 目录名生成用了 `tr`,拼成单横线 | 用 `sed 's|/|--|g'` |
| 加载很慢或 `sox` 警告 | 无碍 | 忽略 |

---

## 附:验证过的基准值(本机实测)

- speech_tokenizer blob `836b7b35…`:`682293092` 字节,SHA-256 与文件名一致。
- 离线加载:`Qwen3TTSTokenizerV2Model`,参数量 `153,714,657`,CPU 约 8 s。
- 1 s 正弦波编解码:code `(13,16)`,解码 24 kHz / 1.04 s,RMS 0.074。
- 主模型 `model.safetensors` 全量:`3,857,413,744` 字节(3.86 GB);`speech_tokenizer/model.safetensors`:`682,293,092` 字节(682 MB)。
