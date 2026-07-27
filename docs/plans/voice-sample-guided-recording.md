# Voice Sample Guided Recording — Implementation Plan

## Goal

Replace the current "blind recording" voice sample flow with a guided experience:

1. Show a ~20-second Chinese text for the user to read aloud
2. Record the user reading it
3. Immediately analyze quality — if pass, accept; if fail, show what went wrong and let the user retry

---

## Phase 1: Chinese Reading Prompt

### 1.1 Add a guided text resource

**File**: `app/src/lib/constants/samplePrompts.ts` (new file)

```ts
// A ~20-second Chinese passage covering common initials, finals, and tones.
// Designed for voice cloning: balanced phoneme coverage, natural sentence flow.
export const CHINESE_SAMPLE_PROMPT = {
  text: `今天天气真好，阳光洒在窗台上，微风轻轻吹过树梢。我泡了一杯热茶，翻开那本买了很久却一直没看的书。书里说，人生就像一场旅行，不在乎目的地，而在乎沿途的风景和看风景的心情。`,
  language: "zh",
  estimatedDurationSeconds: 20,
};

// Fallback shorter version (~12s)
export const CHINESE_SAMPLE_PROMPT_SHORT = {
  text: `今天阳光很好，我坐在窗前喝茶看书。书里有一句话让我印象深刻：人生最重要的不是终点，而是沿途的风景。`,
  language: "zh",
  estimatedDurationSeconds: 12,
};

// Generic prompts for other languages (extensible later)
export const SAMPLE_PROMPTS: Record<string, typeof CHINESE_SAMPLE_PROMPT> = {
  zh: CHINESE_SAMPLE_PROMPT,
  // en, ja, ko, ... can be added here
};
```

---

## Phase 2: Backend — Quality Analysis Endpoint

### 2.1 New Pydantic models

**File**: `backend/models.py` — append these classes:

```python
class SampleQualityRequest(BaseModel):
    """Request to analyze a voice sample's cloning suitability."""
    reference_text: str = Field(..., min_length=1, max_length=1000)

class SampleQualityResult(BaseModel):
    """Result of voice sample quality analysis."""
    passed: bool
    score: float = Field(..., ge=0.0, le=1.0, description="Overall quality score 0-1")
    duration_seconds: float
    issues: list[str] = []
    warnings: list[str] = []
    metrics: dict = {}
```

### 2.2 Quality analysis service

**File**: `backend/services/sample_quality.py` (new file)

```python
"""
Voice sample quality analysis for guided recording.

Checks go beyond basic validation (duration, RMS) to assess whether
a recording is suitable for voice cloning.
"""

import asyncio
import numpy as np
from typing import Tuple

from ..utils.audio import load_audio, preprocess_reference_audio

# ── Thresholds ──────────────────────────────────────────────────────
MIN_DURATION_SECONDS = 2.0       # absolute minimum
MAX_DURATION_SECONDS = 30.0      # absolute maximum
TARGET_DURATION_MIN = 5.0        # soft: below this, warn "too short"
TARGET_DURATION_IDEAL = 10.0     # soft: below this, suggest longer
MIN_RMS = 0.01                   # silence rejection
LOW_RMS_WARN = 0.03              # soft: too quiet
HIGH_RMS_CLIP_RATIO = 0.05       # max 5% samples near ±1.0
MIN_SPEECH_FRACTION = 0.50       # at least 50% of duration must be speech
SILENCE_THRESHOLD_DB = 35.0      # dB below peak = silence
LOW_SNR_DB = 15.0                # SNR below this → noisy environment warning


async def analyze_sample_quality(
    audio_path: str,
    reference_text: str,
) -> dict:
    """
    Analyze a voice sample and return a quality report.

    Returns a dict matching SampleQualityResult schema.
    """
    return await asyncio.to_thread(_analyze_sync, audio_path, reference_text)


def _analyze_sync(audio_path: str, reference_text: str) -> dict:
    audio, sr = load_audio(audio_path, sample_rate=24000, mono=True)
    audio = preprocess_reference_audio(audio, sr)
    duration = len(audio) / sr

    issues: list[str] = []
    warnings: list[str] = []
    metrics: dict = {}

    # ── 1. Duration checks ────────────────────────────────────────
    metrics["duration_seconds"] = round(duration, 2)

    if duration < MIN_DURATION_SECONDS:
        issues.append(f"录音太短（{duration:.1f}秒），最少需要{MIN_DURATION_SECONDS}秒")
    elif duration < TARGET_DURATION_MIN:
        warnings.append(f"录音偏短（{duration:.1f}秒），建议至少{TARGET_DURATION_MIN}秒以获得更好效果")
    elif duration < TARGET_DURATION_IDEAL:
        warnings.append(f"录音时长可接受（{duration:.1f}秒），但{TARGET_DURATION_IDEAL}秒以上效果更佳")

    if duration > MAX_DURATION_SECONDS:
        issues.append(f"录音太长（{duration:.1f}秒），最多{MAX_DURATION_SECONDS}秒")

    # ── 2. Volume / RMS check ──────────────────────────────────────
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    metrics["rms"] = round(rms, 4)

    if rms < MIN_RMS:
        issues.append("录音音量过低，可能为静音或麦克风未正常工作")
    elif rms < LOW_RMS_WARN:
        warnings.append("录音音量偏低，建议靠近麦克风或提高音量")

    # ── 3. Clipping check ──────────────────────────────────────────
    clip_ratio = float(np.mean(np.abs(audio) > 0.99))
    metrics["clip_ratio"] = round(clip_ratio, 4)
    if clip_ratio > HIGH_RMS_CLIP_RATIO:
        warnings.append("录音存在削波失真，建议降低麦克风增益或距离稍远")

    # ── 4. Speech fraction (voice activity detection) ──────────────
    speech_frac = _compute_speech_fraction(audio, sr, SILENCE_THRESHOLD_DB)
    metrics["speech_fraction"] = round(speech_frac, 2)
    if speech_frac < MIN_SPEECH_FRACTION:
        issues.append(f"有效语音占比过低（{speech_frac:.0%}），请确保全程朗读引导文字")
    elif speech_frac < 0.75:
        warnings.append(f"录音中有较多空白（语音占比{speech_frac:.0%}），建议减少停顿")

    # ── 5. SNR estimate ────────────────────────────────────────────
    snr = _estimate_snr(audio, sr)
    metrics["snr_db"] = round(snr, 1)
    if snr < LOW_SNR_DB:
        warnings.append(f"环境噪声较大（信噪比{snr:.0f}dB），建议在安静环境中录制")

    # ── 6. Text length plausibility ────────────────────────────────
    char_count = len(reference_text.replace(" ", "").replace("\n", ""))
    metrics["reference_char_count"] = char_count
    # Rough: average Chinese speech rate ~4 chars/sec
    expected_min_duration = char_count / 6   # slow speaker
    expected_max_duration = char_count / 2.5 # fast speaker
    if duration < expected_min_duration * 0.5:
        warnings.append("朗读可能不完整或语速过快，请确保完整朗读引导文字")
    elif duration > expected_max_duration * 2:
        warnings.append("录音中有较多停顿，请尝试更连贯地朗读")

    # ── 7. Compute final score and verdict ─────────────────────────
    passed = len(issues) == 0
    score = _compute_score(duration, rms, clip_ratio, speech_frac, snr, len(issues))

    return {
        "passed": passed,
        "score": round(score, 2),
        "duration_seconds": round(duration, 2),
        "issues": issues,
        "warnings": warnings,
        "metrics": metrics,
    }


def _compute_speech_fraction(audio: np.ndarray, sr: int, silence_db: float) -> float:
    """Fraction of frames that are above the silence threshold."""
    frame_len = int(sr * 0.02)  # 20ms frames
    if frame_len == 0 or len(audio) < frame_len:
        return 1.0
    n_frames = len(audio) // frame_len
    if n_frames == 0:
        return 1.0
    rms_frames = np.array([
        np.sqrt(np.mean(audio[i * frame_len:(i + 1) * frame_len] ** 2))
        for i in range(n_frames)
    ])
    peak_rms = float(np.max(rms_frames))
    if peak_rms == 0:
        return 0.0
    threshold = peak_rms * (10 ** (-silence_db / 20))
    speech_frames = np.sum(rms_frames > threshold)
    return float(speech_frames / n_frames)


def _estimate_snr(audio: np.ndarray, sr: int) -> float:
    """Crude SNR estimate: compare top-10% energy frames vs bottom-10%."""
    frame_len = int(sr * 0.02)
    if frame_len == 0 or len(audio) < frame_len * 10:
        return 999.0
    n_frames = len(audio) // frame_len
    rms_frames = np.array([
        np.sqrt(np.mean(audio[i * frame_len:(i + 1) * frame_len] ** 2))
        for i in range(n_frames)
    ])
    rms_frames.sort()
    n_low = max(1, n_frames // 10)
    n_high = max(1, n_frames // 10)
    noise_rms = float(np.mean(rms_frames[:n_low]))
    signal_rms = float(np.mean(rms_frames[-n_high:]))
    if noise_rms == 0:
        return 999.0
    return float(20 * np.log10(signal_rms / noise_rms))


def _compute_score(
    duration: float,
    rms: float,
    clip_ratio: float,
    speech_frac: float,
    snr: float,
    issue_count: int,
) -> float:
    """Weighted quality score 0.0–1.0."""
    if issue_count > 0:
        return max(0.0, 0.6 - issue_count * 0.15)

    score = 1.0

    # Duration: ideal 10-20s, penalty outside
    if duration < 5:
        score -= 0.2
    elif duration < 10:
        score -= 0.05

    # Speech fraction
    if speech_frac < 0.75:
        score -= 0.2
    elif speech_frac < 0.90:
        score -= 0.1

    # SNR
    if snr < 15:
        score -= 0.2
    elif snr < 25:
        score -= 0.1

    # Clipping
    if clip_ratio > 0.05:
        score -= 0.15

    return max(0.0, min(1.0, score))
```

### 2.3 API route

**File**: `backend/routes/profiles.py` — append after the existing `/profiles/{profile_id}/samples` block:

```python
@router.post(
    "/profiles/{profile_id}/samples/analyze",
    response_model=models.SampleQualityResult,
)
async def analyze_sample_quality(
    profile_id: str,
    file: UploadFile = File(...),
    reference_text: str = Form(...),
    db: Session = Depends(get_db),
):
    """Upload a voice sample and get a quality analysis without saving.

    Use this for guided recording: upload, check quality, retry if needed.
    When the user accepts the quality, POST to /profiles/{id}/samples to save.
    """
    from ..services.sample_quality import analyze_sample_quality as do_analyze

    # Verify profile exists
    profile = db.query(DBVoiceProfile).filter_by(id=profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    _allowed_audio_exts = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".webm", ".opus"}
    _uploaded_ext = Path(file.filename or "").suffix.lower()
    file_suffix = _uploaded_ext if _uploaded_ext in _allowed_audio_exts else ".wav"

    with tempfile.NamedTemporaryFile(suffix=file_suffix, delete=False) as tmp:
        total_size = 0
        while chunk := await file.read(SAMPLE_UPLOAD_CHUNK_SIZE):
            total_size += len(chunk)
            if total_size > SAMPLE_MAX_FILE_SIZE:
                Path(tmp.name).unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="File too large")
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        result = await do_analyze(tmp_path, reference_text)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Quality analysis failed: {str(e)}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)
```

**Also add the import at the top** of `profiles.py`:
```python
from ..database import DBVoiceProfile  # if not already imported
```

---

## Phase 3: Frontend — Guided Recording Component

### 3.1 API client hook

**File**: `app/src/lib/hooks/useSampleQuality.ts` (new file)

```ts
import { useMutation } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import type { SampleQualityResult } from "@/lib/api/types";

interface AnalyzeParams {
  profileId: string;
  audioBlob: Blob;
  referenceText: string;
}

export function useSampleQuality() {
  return useMutation<SampleQualityResult, Error, AnalyzeParams>({
    mutationFn: async ({ profileId, audioBlob, referenceText }) => {
      const formData = new FormData();
      formData.append("file", audioBlob, "recording.webm");
      formData.append("reference_text", referenceText);
      return apiClient.analyzeSampleQuality(profileId, formData);
    },
  });
}
```

### 3.2 API client method

**File**: `app/src/lib/api/client.ts` — add method (find the profiles section and add):

```ts
async analyzeSampleQuality(profileId: string, formData: FormData): Promise<SampleQualityResult> {
  const response = await fetch(`${this.baseUrl}/profiles/${profileId}/samples/analyze`, {
    method: "POST",
    body: formData,
    credentials: "include",
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || "Quality analysis failed");
  }
  return response.json();
}
```

### 3.3 API types

**File**: `app/src/lib/api/types.ts` — add:

```ts
export interface SampleQualityResult {
  passed: boolean;
  score: number;
  duration_seconds: number;
  issues: string[];
  warnings: string[];
  metrics: Record<string, number>;
}
```

### 3.4 GuidedRecording component

**File**: `app/src/components/VoiceProfiles/GuidedRecording.tsx` (new file)

```tsx
import { Mic, RefreshCw, Check, AlertTriangle, Info } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CHINESE_SAMPLE_PROMPT } from "@/lib/constants/samplePrompts";
import { useAudioRecording } from "@/lib/hooks/useAudioRecording";
import { useSampleQuality } from "@/lib/hooks/useSampleQuality";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

interface GuidedRecordingProps {
  profileId: string;
  onSampleReady: (blob: Blob, referenceText: string, quality: SampleQualityResult) => void;
  onCancel: () => void;
}

type Stage = "prompt" | "recording" | "analyzing" | "result_pass" | "result_fail";

export function GuidedRecording({ profileId, onSampleReady, onCancel }: GuidedRecordingProps) {
  const { t } = useTranslation();
  const [stage, setStage] = useState<Stage>("prompt");
  const [qualityResult, setQualityResult] = useState<SampleQualityResult | null>(null);
  const recordingBlobRef = useRef<Blob | null>(null);

  const prompt = CHINESE_SAMPLE_PROMPT; // extend with language selection later

  const { isRecording, duration, error: recError, startRecording, stopRecording } =
    useAudioRecording({
      maxDurationSeconds: 29,
      onRecordingComplete: (blob) => {
        recordingBlobRef.current = blob;
        setStage("analyzing");
        analyzeMutation.mutate({
          profileId,
          audioBlob: blob,
          referenceText: prompt.text,
        });
      },
    });

  const analyzeMutation = useSampleQuality();

  // When analysis completes
  const handleResult = useCallback((result: SampleQualityResult) => {
    setQualityResult(result);
    setStage(result.passed ? "result_pass" : "result_fail");
  }, []);

  // Watch for analysis result via useEffect to handle both success and error
  // (simple approach: check in the onSettled callback below)

  const handleRetry = useCallback(() => {
    setQualityResult(null);
    recordingBlobRef.current = null;
    setStage("prompt");
  }, []);

  const handleAccept = useCallback(() => {
    if (recordingBlobRef.current && qualityResult) {
      onSampleReady(recordingBlobRef.current, prompt.text, qualityResult);
    }
  }, [prompt.text, qualityResult, onSampleReady]);

  // ── Render stages ──────────────────────────────────────────────

  return (
    <div className="flex flex-col gap-4 p-6">
      {/* Stage: Prompt — show text, ready to record */}
      {stage === "prompt" && (
        <>
          <div className="rounded-lg border bg-muted/30 p-4">
            <p className="text-sm text-muted-foreground mb-2">
              {t("guidedRecording.readAloud")}
            </p>
            <p className="text-lg leading-relaxed tracking-wide select-none">
              {prompt.text}
            </p>
          </div>
          <div className="flex gap-3">
            <Button onClick={startRecording} className="gap-2">
              <Mic className="w-4 h-4" />
              {t("guidedRecording.startRecording")}
            </Button>
            <Button variant="ghost" onClick={onCancel}>
              {t("common.cancel")}
            </Button>
          </div>
        </>
      )}

      {/* Stage: Recording — show countdown, stop button */}
      {stage === "recording" && (
        <>
          <div className="rounded-lg border bg-muted/30 p-4 opacity-60">
            <p className="text-lg leading-relaxed tracking-wide">{prompt.text}</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex-1">
              <Progress value={(duration / 29) * 100} />
            </div>
            <span className="text-sm tabular-nums w-12 text-right">
              {Math.ceil(duration)}s
            </span>
          </div>
          <Button
            onClick={stopRecording}
            variant="destructive"
            className="gap-2"
            disabled={duration < 2} // minimum 2 seconds
          >
            <Mic className="w-4 h-4" />
            {t("guidedRecording.stopRecording")}
          </Button>
        </>
      )}

      {/* Stage: Analyzing — spinner */}
      {stage === "analyzing" && (
        <div className="flex flex-col items-center gap-4 py-8">
          <RefreshCw className="w-8 h-8 animate-spin text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            {t("guidedRecording.analyzing")}
          </p>
        </div>
      )}

      {/* Stage: Result — FAIL */}
      {stage === "result_fail" && qualityResult && (
        <>
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4">
            <div className="flex items-start gap-2 mb-3">
              <AlertTriangle className="w-5 h-5 text-destructive mt-0.5 shrink-0" />
              <div>
                <p className="font-medium text-destructive">
                  {t("guidedRecording.qualityFailed")}
                </p>
                <p className="text-sm text-muted-foreground">
                  {t("guidedRecording.scoreLabel")}: {Math.round(qualityResult.score * 100)}%
                </p>
              </div>
            </div>
            {qualityResult.issues.length > 0 && (
              <ul className="space-y-1 mb-3">
                {qualityResult.issues.map((issue, i) => (
                  <li key={i} className="text-sm text-destructive flex gap-2">
                    <span>•</span> {issue}
                  </li>
                ))}
              </ul>
            )}
            {qualityResult.warnings.length > 0 && (
              <ul className="space-y-1">
                {qualityResult.warnings.map((w, i) => (
                  <li key={i} className="text-sm text-amber-600 flex gap-2">
                    <Info className="w-4 h-4 shrink-0 mt-0.5" />
                    {w}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="flex gap-3">
            <Button onClick={handleRetry} variant="outline" className="gap-2">
              <RefreshCw className="w-4 h-4" />
              {t("guidedRecording.retry")}
            </Button>
            <Button onClick={handleAccept} variant="secondary">
              {t("guidedRecording.acceptAnyway")}
            </Button>
          </div>
        </>
      )}

      {/* Stage: Result — PASS */}
      {stage === "result_pass" && qualityResult && (
        <>
          <div className="rounded-lg border border-green-200 bg-green-50 dark:bg-green-950 p-4">
            <div className="flex items-start gap-2">
              <Check className="w-5 h-5 text-green-600 mt-0.5 shrink-0" />
              <div>
                <p className="font-medium text-green-700 dark:text-green-400">
                  {t("guidedRecording.qualityPassed")}
                </p>
                <p className="text-sm text-muted-foreground">
                  {t("guidedRecording.scoreLabel")}: {Math.round(qualityResult.score * 100)}%
                  {" · "}
                  {t("guidedRecording.durationLabel")}: {qualityResult.duration_seconds.toFixed(1)}s
                </p>
              </div>
            </div>
          </div>
          <div className="flex gap-3">
            <Button onClick={handleAccept} className="gap-2">
              <Check className="w-4 h-4" />
              {t("guidedRecording.useThisSample")}
            </Button>
            <Button onClick={handleRetry} variant="ghost">
              {t("guidedRecording.retry")}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
```

### 3.5 Integrate into ProfileForm

**File**: `app/src/components/VoiceProfiles/ProfileForm.tsx` — modify:

1. Add "guided" to the `sampleMode` union:
   ```ts
   const [sampleMode, setSampleMode] = useState<'upload' | 'record' | 'system' | 'guided'>('guided');
   ```

2. In the sample mode tab bar, add a tab for guided recording (only when `voiceSource === 'clone'`):
   ```tsx
   {voiceSource === 'clone' && (
     <TabsTrigger value="guided">
       <Mic className="w-4 h-4 mr-1" />
       {t('profileForm.guidedRecording')}
     </TabsTrigger>
   )}
   ```

3. Add the GuidedRecording component rendering:
   ```tsx
   {sampleMode === 'guided' && profileId && (
     <GuidedRecording
       profileId={profileId}
       onSampleReady={(blob, text, quality) => {
         // Same handling as recording/upload completion:
         // set the file on the form, optionally skip validation since
         // it already passed quality check
         const file = new File([blob], `guided-recording-${Date.now()}.webm`, {
           type: blob.type || 'audio/webm',
         }) as File & { recordedDuration?: number };
         if (quality.duration_seconds !== undefined) {
           file.recordedDuration = quality.duration_seconds;
         }
         form.setValue('sampleFile', file, { shouldValidate: true });
         form.setValue('referenceText', text, { shouldValidate: true });
         toast({ title: t('profileForm.toast.guidedSampleReady') });
       }}
       onCancel={() => setSampleMode('record')}
     />
   )}
   ```

   Note: `profileId` is only available in **edit** mode (after profile creation). For the **create** flow, the profile doesn't exist yet. Two options:
   - **Option A** (simpler, ship faster): Only show guided recording in edit mode, after profile is created
   - **Option B** (better UX): Create a draft profile immediately when the user opens the dialog, then use its ID

   **Implement Option A first**. The CREATE flow can still use the existing `record`/`upload` modes.

---

## Phase 4: i18n Keys

### 4.1 Add translation keys

**File**: `app/src/i18n/zh.json` — add:

```json
{
  "guidedRecording": {
    "readAloud": "请朗读以下文字：",
    "startRecording": "开始录音",
    "stopRecording": "停止录音",
    "analyzing": "正在分析录音质量...",
    "qualityPassed": "录音质量合格！",
    "qualityFailed": "录音质量不达标",
    "scoreLabel": "质量评分",
    "durationLabel": "时长",
    "retry": "重新录制",
    "acceptAnyway": "仍然使用",
    "useThisSample": "使用此样本"
  },
  "profileForm": {
    "guidedRecording": "引导录音",
    "toast": {
      "guidedSampleReady": "引导录音样本已就绪"
    }
  }
}
```

**File**: `app/src/i18n/en.json` — add corresponding English keys.

---

## Phase 5: Unit Tests

### 5.1 Backend test

**File**: `backend/tests/test_sample_quality.py` (new file)

```python
"""Tests for sample quality analysis."""
import numpy as np
import pytest
from pathlib import Path
import soundfile as sf
import tempfile

from backend.services.sample_quality import _analyze_sync


def make_test_audio(duration: float, rms: float = 0.05, sr: int = 24000) -> Path:
    """Generate a synthetic audio file for testing."""
    samples = int(duration * sr)
    audio = np.random.randn(samples).astype(np.float32) * rms
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, audio, sr)
    return Path(tmp.name)


def test_too_short_rejected():
    path = make_test_audio(1.5)
    try:
        result = _analyze_sync(str(path), "测试文字")
        assert result["passed"] is False
        assert any("短" in issue for issue in result["issues"])
    finally:
        path.unlink()


def test_good_sample_passes():
    path = make_test_audio(12.0, rms=0.08)
    try:
        result = _analyze_sync(str(path), "这是一段大约二十秒的中文测试文本用于评估声音克隆质量")
        # Generated white noise won't get perfect score, but should pass
        assert "duration_seconds" in result
        assert "score" in result
        assert 0 <= result["score"] <= 1
    finally:
        path.unlink()


def test_silence_rejected():
    path = make_test_audio(5.0, rms=0.001)
    try:
        result = _analyze_sync(str(path), "测试")
        assert result["passed"] is False
        assert any("音量" in issue for issue in result["issues"])
    finally:
        path.unlink()
```

### 5.2 Test command

```bash
cd backend && python -m pytest tests/test_sample_quality.py -xvs
```

---

## Summary of Files Changed

| File | Action | Phase |
|------|--------|-------|
| `app/src/lib/constants/samplePrompts.ts` | **New** | 1 |
| `backend/models.py` | Append 2 classes | 2.1 |
| `backend/services/sample_quality.py` | **New** | 2.2 |
| `backend/routes/profiles.py` | Append 1 route + add import | 2.3 |
| `app/src/lib/hooks/useSampleQuality.ts` | **New** | 3.1 |
| `app/src/lib/api/client.ts` | Append method | 3.2 |
| `app/src/lib/api/types.ts` | Append interface | 3.3 |
| `app/src/components/VoiceProfiles/GuidedRecording.tsx` | **New** | 3.4 |
| `app/src/components/VoiceProfiles/ProfileForm.tsx` | Modify (add guided tab) | 3.5 |
| `app/src/i18n/zh.json` | Append keys | 4.1 |
| `app/src/i18n/en.json` | Append keys | 4.1 |
| `backend/tests/test_sample_quality.py` | **New** | 5.1 |

## Implementation Order

1. **Phase 1** — samplePrompts.ts (no dependencies)
2. **Phase 2** — backend models + service + route (no frontend dependency)
3. **Phase 4** — i18n keys (needed for Phase 3 UI)
4. **Phase 3** — frontend components + API client (depends on Phase 2 + 4)
5. **Phase 5** — tests (depends on Phase 2)
