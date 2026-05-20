"""Unit-тесты NudeNetDetector в сценарии «модели нет на диске»."""

from __future__ import annotations

from app.services.nudenet_singleton import NudeNetDetector


def test_detector_unavailable_when_file_missing() -> None:
    detector = NudeNetDetector("/tmp/definitely_nonexistent_model_xyz.onnx")
    assert detector.is_available is False
    assert detector.score(b"fake-bytes") is None


def test_score_returns_none_on_unavailable() -> None:
    detector = NudeNetDetector("")
    assert detector.is_available is False
    assert detector.score(b"\x89PNG\r\n\x1a\n") is None
