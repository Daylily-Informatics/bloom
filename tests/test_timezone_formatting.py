from __future__ import annotations

from datetime import UTC, datetime

from bloom_lims.gui.jinja import templates


def _render(template_body: str, **kwargs) -> str:
    template = templates.from_string(template_body)
    return template.render(**kwargs)


def test_format_dt_converts_utc_to_user_display_timezone():
    rendered = _render(
        "{{ value | format_dt('standard') }}",
        value=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
        udat={"display_timezone": "America/New_York"},
    )
    assert rendered.startswith("2026-03-09 08:00:00")


def test_format_dt_defaults_to_utc_for_invalid_timezone():
    rendered = _render(
        "{{ value | format_dt('standard') }}",
        value=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
        udat={"display_timezone": "Not/A_Timezone"},
    )
    assert rendered.startswith("2026-03-09 12:00:00")


def test_dt_local_input_treats_naive_timestamp_as_utc():
    rendered = _render(
        "{{ value | dt_local_input }}",
        value=datetime(2026, 1, 1, 0, 0, 0),
        udat={"display_timezone": "America/Los_Angeles"},
    )
    assert rendered == "2025-12-31T16:00:00"
