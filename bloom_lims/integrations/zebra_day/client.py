"""Typed zebra_day integration wrapper for Bloom."""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:  # pragma: no cover
    from zebra_day.client import PrinterRecord, ZebraDayApiClient
else:
    PrinterRecord = Any
    ZebraDayApiClient = Any

from bloom_lims.config import BloomSettings, get_settings

logger = logging.getLogger(__name__)


class ZebraDayIntegrationError(RuntimeError):
    """Raised when Bloom cannot safely use the configured zebra_day service."""


def _load_zebra_day_client_types() -> tuple[type[Any], type[Any]]:
    try:
        client_mod = importlib.import_module("zebra_day.client")
    except ImportError as exc:
        raise ZebraDayIntegrationError(
            "zebra-day is not installed; install zebra-day in the active Bloom environment to use printer integration"
        ) from exc

    return client_mod.PrinterRecord, client_mod.ZebraDayApiClient


def _display_name(printer: PrinterRecord) -> str:
    return str(printer.printer_name or "").strip() or printer.printer_id


class ZebraDayService:
    """Thin service wrapper around the zebra_day API-backed client."""

    def __init__(self, settings: BloomSettings | None = None):
        self.settings = settings or get_settings()
        self.config = self.settings.zebra_day

    @property
    def base_url(self) -> str:
        return str(self.config.base_url or "").strip().rstrip("/")

    @property
    def admin_url(self) -> str | None:
        return self.base_url or None

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url)

    @property
    def has_service_token(self) -> bool:
        return bool(str(self.config.token or "").strip())

    def _client(self) -> ZebraDayApiClient:
        if not self.is_configured:
            raise ZebraDayIntegrationError("zebra_day.base_url is not configured")

        _, zebra_day_api_client_cls = _load_zebra_day_client_types()
        headers = {"accept": "application/json"}
        if self.has_service_token:
            headers["authorization"] = f"Bearer {self.config.token}"

        http_client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            follow_redirects=True,
            timeout=float(self.config.timeout_seconds),
            verify=self.config.verify_ssl,
        )
        return zebra_day_api_client_cls(
            base_url=self.base_url,
            api_key=self.config.token or None,
            verify_ssl=self.config.verify_ssl,
            client=http_client,
        )

    def list_labs(self) -> list[str]:
        with self._client() as client:
            return list(client.list_labs())

    def list_printers(self, lab: str) -> list[PrinterRecord]:
        with self._client() as client:
            return list(client.list_printers(lab))

    def list_label_profiles(self) -> list[dict[str, Any]]:
        with self._client() as client:
            return list(client.list_label_profiles())

    def build_printer_preferences(
        self, selected_lab: str | None = None
    ) -> dict[str, Any]:
        if not self.is_configured:
            return {
                "status": "not_configured",
                "error_detail": "zebra_day.base_url is not configured",
                "print_lab": [],
                "printer_name": [],
                "printer_options": [],
                "label_zpl_style": [],
                "selected_lab": "",
            }

        try:
            labs = self.list_labs()
            active_lab = str(selected_lab or "").strip()
            if active_lab not in labs:
                active_lab = labs[0] if labs else ""
            printers = self.list_printers(active_lab) if active_lab else []
            profiles = self.list_label_profiles()
        except Exception as exc:
            logger.warning("Failed to load zebra_day printer preferences: %s", exc)
            return {
                "status": "error",
                "error_detail": str(exc),
                "print_lab": [],
                "printer_name": [],
                "printer_options": [],
                "label_zpl_style": [],
                "selected_lab": "",
            }

        printer_options = [
            {
                "value": printer.printer_id,
                "label": _display_name(printer),
                "lab": printer.lab,
                "ip_address": printer.ip_address,
            }
            for printer in printers
        ]
        label_profiles = sorted(
            {
                str(item.get("profile_name") or "").strip()
                for item in profiles
                if str(item.get("profile_name") or "").strip()
            }
        )

        return {
            "status": "ok",
            "error_detail": "",
            "print_lab": labs,
            "printer_name": [item["value"] for item in printer_options],
            "printer_options": printer_options,
            "label_zpl_style": label_profiles,
            "selected_lab": active_lab,
        }

    def submit_print_job(
        self,
        *,
        lab: str,
        printer_id: str,
        label_zpl_style: str,
        euid: str,
        alt_a: str = "",
        alt_b: str = "",
        alt_c: str = "",
        alt_d: str = "",
        alt_e: str = "",
        alt_f: str = "",
        print_n: int = 1,
    ) -> dict[str, Any]:
        with self._client() as client:
            return dict(
                client.submit_print_job(
                    lab=lab,
                    printer=printer_id,
                    label_zpl_style=label_zpl_style or None,
                    uid_barcode=euid,
                    alt_a=alt_a,
                    alt_b=alt_b,
                    alt_c=alt_c,
                    alt_d=alt_d,
                    alt_e=alt_e,
                    alt_f=alt_f,
                    copies=int(print_n or 1),
                )
            )
