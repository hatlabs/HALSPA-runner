"""Tests for environment-driven configuration."""

import importlib

import pytest

from halspa_runner import config


@pytest.mark.parametrize("raw", ["inf", "-inf", "nan", "not-a-number"])
def test_non_finite_timer_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch, raw: str,
) -> None:
    """A timer must never be disabled by a bad environment value.

    inf would stop the watchdog waking at all, and nan defeats the clamp
    because every comparison against it is false.
    """
    monkeypatch.setenv("HALSPA_RUNNER_UI_PICO_HEARTBEAT_INTERVAL", raw)
    reloaded = importlib.reload(config)
    try:
        assert reloaded.UI_PICO_HEARTBEAT_INTERVAL == pytest.approx(2.5)
    finally:
        monkeypatch.delenv("HALSPA_RUNNER_UI_PICO_HEARTBEAT_INTERVAL")
        importlib.reload(config)


def test_negative_interval_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HALSPA_RUNNER_UI_PICO_HEARTBEAT_INTERVAL", "-1")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.UI_PICO_HEARTBEAT_INTERVAL > 0
    finally:
        monkeypatch.delenv("HALSPA_RUNNER_UI_PICO_HEARTBEAT_INTERVAL")
        importlib.reload(config)


def test_max_missed_is_at_least_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """A limit of zero would tear the link down before any ping is sent."""
    monkeypatch.setenv("HALSPA_RUNNER_UI_PICO_HEARTBEAT_MAX_MISSED", "0")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.UI_PICO_HEARTBEAT_MAX_MISSED >= 1
    finally:
        monkeypatch.delenv("HALSPA_RUNNER_UI_PICO_HEARTBEAT_MAX_MISSED")
        importlib.reload(config)
