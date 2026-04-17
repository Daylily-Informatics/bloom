from __future__ import annotations

from types import SimpleNamespace

import pytest

from bloom_lims.config import BloomSettings, ZebraDaySettings
from bloom_lims.integrations.zebra_day.client import (
    ZebraDayIntegrationError,
    ZebraDayService,
)
from bloom_lims.observability import BloomObservabilityStore


class _FakeZebraClient:
    def __init__(self, *, labs=None, printers=None, profiles=None, print_response=None):
        self._labs = labs or []
        self._printers = printers or {}
        self._profiles = profiles or []
        self._print_response = print_response or {"success": True, "message": "queued"}
        self.last_submit_payload = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def list_labs(self):
        return list(self._labs)

    def list_printers(self, lab):
        return list(self._printers.get(lab, []))

    def list_label_profiles(self):
        return list(self._profiles)

    def submit_print_job(self, **kwargs):
        self.last_submit_payload = dict(kwargs)
        return dict(self._print_response)


def _printer(*, lab: str, printer_id: str, printer_name: str, ip_address: str):
    return SimpleNamespace(
        lab=lab,
        printer_id=printer_id,
        printer_name=printer_name,
        ip_address=ip_address,
    )


def test_zebra_day_service_reports_not_configured_without_base_url():
    settings = BloomSettings(zebra_day=ZebraDaySettings(base_url="", token=""))

    payload = ZebraDayService(settings).build_printer_preferences("BLOOM")

    assert payload["status"] == "not_configured"
    assert payload["print_lab"] == []
    assert payload["printer_options"] == []


def test_zebra_day_service_builds_printer_preferences(monkeypatch):
    settings = BloomSettings(
        zebra_day=ZebraDaySettings(
            base_url="https://zebra-day.example.org",
            token="internal-token",
        )
    )
    fake_client = _FakeZebraClient(
        labs=["BLOOM", "QA"],
        printers={
            "BLOOM": [
                _printer(
                    lab="BLOOM",
                    printer_id="printer-1",
                    printer_name="North Bench",
                    ip_address="10.0.0.12",
                )
            ]
        },
        profiles=[
            {"profile_name": "tube_2inX1in"},
            {"profile_name": "tube_2inX1in"},
            {"profile_name": "plate_4inX6in"},
        ],
    )
    service = ZebraDayService(settings)
    monkeypatch.setattr(service, "_client", lambda: fake_client)

    payload = service.build_printer_preferences("BLOOM")

    assert payload["status"] == "ok"
    assert payload["print_lab"] == ["BLOOM", "QA"]
    assert payload["printer_name"] == ["printer-1"]
    assert payload["printer_options"] == [
        {
            "value": "printer-1",
            "label": "North Bench",
            "lab": "BLOOM",
            "ip_address": "10.0.0.12",
        }
    ]
    assert payload["label_zpl_style"] == ["plate_4inX6in", "tube_2inX1in"]
    assert payload["selected_lab"] == "BLOOM"


def test_zebra_day_service_submits_server_side_print_jobs(monkeypatch):
    settings = BloomSettings(
        zebra_day=ZebraDaySettings(
            base_url="https://zebra-day.example.org",
            token="internal-token",
        )
    )
    fake_client = _FakeZebraClient(
        print_response={"success": True, "message": "queued"}
    )
    service = ZebraDayService(settings)
    monkeypatch.setattr(service, "_client", lambda: fake_client)

    payload = service.submit_print_job(
        lab="BLOOM",
        printer_id="printer-7",
        label_zpl_style="tube_2inX1in",
        euid="E123",
        alt_a="a",
        alt_b="b",
        alt_c="c",
        alt_d="d",
        alt_e="e",
        alt_f="f",
        print_n=2,
    )

    assert payload == {"success": True, "message": "queued"}
    assert fake_client.last_submit_payload == {
        "lab": "BLOOM",
        "printer": "printer-7",
        "label_zpl_style": "tube_2inX1in",
        "uid_barcode": "E123",
        "alt_a": "a",
        "alt_b": "b",
        "alt_c": "c",
        "alt_d": "d",
        "alt_e": "e",
        "alt_f": "f",
        "copies": 2,
    }


def test_zebra_day_service_requires_optional_dependency_when_configured(monkeypatch):
    settings = BloomSettings(
        zebra_day=ZebraDaySettings(
            base_url="https://zebra-day.example.org",
            token="internal-token",
        )
    )
    service = ZebraDayService(settings)

    def _missing_client(_name: str):
        raise ImportError("No module named 'zebra_day'")

    monkeypatch.setattr(
        "bloom_lims.integrations.zebra_day.client.importlib.import_module",
        _missing_client,
    )

    with pytest.raises(
        ZebraDayIntegrationError,
        match=r"install zebra-day in the active Bloom environment",
    ):
        service.submit_print_job(
            lab="BLOOM",
            printer_id="printer-7",
            label_zpl_style="tube_2inX1in",
            euid="E123",
        )


def test_observability_store_treats_zebra_day_as_dependency_not_managed_service(
    monkeypatch,
):
    settings = BloomSettings(
        atlas={"base_url": "https://atlas.example.org", "token": "atlas-token"},
        zebra_day={
            "base_url": "https://zebra-day.example.org",
            "token": "internal-token",
        },
    )
    monkeypatch.setattr("bloom_lims.observability.get_settings", lambda: settings)

    store = BloomObservabilityStore()
    _projection, payload = store.obs_services_snapshot()

    assert "atlas" in payload["dependencies"]["configured_services"]
    assert "zebra_day" in payload["dependencies"]["configured_services"]
    assert payload["managed_services"] == []
