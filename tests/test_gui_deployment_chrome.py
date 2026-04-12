from __future__ import annotations

from types import SimpleNamespace

from bloom_lims.gui.jinja import refresh_template_globals, templates


def test_refresh_template_globals_exposes_deployment_banner(monkeypatch) -> None:
    fake_settings = SimpleNamespace(
        app_name="BLOOM LIMS",
        api=SimpleNamespace(version="1.2.3"),
        ui=SimpleNamespace(
            support_email="support@example.com",
            github_repo_url="https://github.com/Daylily-Informatics/bloom",
            show_environment_chrome=True,
        ),
        aws=SimpleNamespace(
            region="us-west-2",
        ),
        deployment=SimpleNamespace(
            name="staging",
            color="#123456",
            is_production=False,
        ),
    )
    monkeypatch.setattr("bloom_lims.config.get_settings", lambda: fake_settings)

    refresh_template_globals()
    rendered = templates.get_template("modern/base.html").render(
        request=SimpleNamespace(url=SimpleNamespace(path="/")),
        user=None,
        udat=None,
        version="1.2.3",
    )

    assert "STAGING" in rendered
    assert "#123456" in rendered
    assert "/favicon.ico" in rendered
