"""Tests for sample quality analysis."""
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from backend.services.sample_quality import _analyze_sync


def make_test_audio(
    duration: float, rms: float = 0.05, sr: int = 24000
) -> Path:
    """Generate a synthetic audio file for testing."""
    samples = int(duration * sr)
    audio = np.random.randn(samples).astype(np.float32) * rms
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, audio, sr)
    return Path(tmp.name)


def test_too_short_rejected():
    """Very short audio should be rejected."""
    path = make_test_audio(1.5)
    try:
        result = _analyze_sync(str(path), "测试文字")
        assert result["passed"] is False
        assert any("短" in issue for issue in result["issues"])
    finally:
        path.unlink()


def test_good_sample_has_metrics():
    """A normal sample should produce valid metrics."""
    path = make_test_audio(12.0, rms=0.08)
    try:
        result = _analyze_sync(
            str(path),
            "这是一段大约二十秒的中文测试文本用于评估声音克隆质量",
        )
        assert "duration_seconds" in result
        assert result["duration_seconds"] > 0
        assert "score" in result
        assert 0 <= result["score"] <= 1
    finally:
        path.unlink()


def test_silence_rejected():
    """Very quiet audio should be rejected."""
    path = make_test_audio(5.0, rms=0.001)
    try:
        result = _analyze_sync(str(path), "测试")
        assert result["passed"] is False
        assert any("音量" in issue for issue in result["issues"])
    finally:
        path.unlink()


def test_longer_audio_gets_better_score():
    """Longer samples should score higher than very short ones."""
    short_path = make_test_audio(3.0, rms=0.08)
    long_path = make_test_audio(15.0, rms=0.08)
    try:
        short_result = _analyze_sync(str(short_path), "测试文本用于评估")
        long_result = _analyze_sync(
            str(long_path),
            "这是一段大约二十秒的中文测试文本用于评估声音克隆质量",
        )
        # Longer sample should have a higher score
        assert long_result["score"] >= short_result["score"]
    finally:
        short_path.unlink()
        long_path.unlink()
