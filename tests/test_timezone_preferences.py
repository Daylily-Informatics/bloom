from __future__ import annotations

from bloom_lims.gui import deps


def test_get_user_preferences_hydrates_shared_display_timezone(monkeypatch):
    monkeypatch.setattr(
        deps,
        "_load_shared_display_timezone",
        lambda _email: "America/Los_Angeles",
    )
    prefs = deps.get_user_preferences("user@example.com")
    assert prefs["display_timezone"] == "America/Los_Angeles"


def test_normalize_display_timezone_aliases_to_utc():
    assert deps.normalize_display_timezone("GMT") == "UTC"
    assert deps.normalize_display_timezone("UTC") == "UTC"
