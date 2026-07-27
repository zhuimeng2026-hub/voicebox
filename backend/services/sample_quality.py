"""
Voice sample quality analysis for guided recording.

Checks go beyond basic validation (duration, RMS) to assess whether
a recording is suitable for voice cloning.
"""

import asyncio
import numpy as np

from ..utils.audio import load_audio, preprocess_reference_audio

# ── Thresholds ──────────────────────────────────────────────────────
MIN_DURATION_SECONDS = 2.0       # absolute minimum
MAX_DURATION_SECONDS = 30.0      # absolute maximum
TARGET_DURATION_MIN = 5.0        # soft: below this, warn "too short"
TARGET_DURATION_IDEAL = 10.0     # soft: below this, suggest longer
MIN_RMS = 0.01                   # silence rejection
LOW_RMS_WARN = 0.03              # soft: too quiet
HIGH_RMS_CLIP_RATIO = 0.05       # max 5% samples near +/-1.0
MIN_SPEECH_FRACTION = 0.50       # at least 50% of duration must be speech
SILENCE_THRESHOLD_DB = 35.0      # dB below peak = silence
LOW_SNR_DB = 15.0                # SNR below this -> noisy environment warning


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
        issues.append(
            f"录音太短（{duration:.1f}秒），最少需要{MIN_DURATION_SECONDS}秒"
        )
    elif duration < TARGET_DURATION_MIN:
        warnings.append(
            f"录音偏短（{duration:.1f}秒），建议至少{TARGET_DURATION_MIN}秒以获得更好效果"
        )
    elif duration < TARGET_DURATION_IDEAL:
        warnings.append(
            f"录音时长可接受（{duration:.1f}秒），但{TARGET_DURATION_IDEAL}秒以上效果更佳"
        )

    if duration > MAX_DURATION_SECONDS:
        issues.append(
            f"录音太长（{duration:.1f}秒），最多{MAX_DURATION_SECONDS}秒"
        )

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
        issues.append(
            f"有效语音占比过低（{speech_frac:.0%}），请确保全程朗读引导文字"
        )
    elif speech_frac < 0.75:
        warnings.append(
            f"录音中有较多空白（语音占比{speech_frac:.0%}），建议减少停顿"
        )

    # ── 5. SNR estimate ────────────────────────────────────────────
    snr = _estimate_snr(audio, sr)
    metrics["snr_db"] = round(snr, 1)
    if snr < LOW_SNR_DB:
        warnings.append(
            f"环境噪声较大（信噪比{snr:.0f}dB），建议在安静环境中录制"
        )

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


def _compute_speech_fraction(
    audio: np.ndarray, sr: int, silence_db: float
) -> float:
    """Fraction of frames that are above the silence threshold."""
    frame_len = int(sr * 0.02)  # 20ms frames
    if frame_len == 0 or len(audio) < frame_len:
        return 1.0
    n_frames = len(audio) // frame_len
    if n_frames == 0:
        return 1.0
    rms_frames = np.array(
        [
            np.sqrt(np.mean(audio[i * frame_len : (i + 1) * frame_len] ** 2))
            for i in range(n_frames)
        ]
    )
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
    rms_frames = np.array(
        [
            np.sqrt(np.mean(audio[i * frame_len : (i + 1) * frame_len] ** 2))
            for i in range(n_frames)
        ]
    )
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
    """Weighted quality score 0.0-1.0."""
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
