from __future__ import annotations

from types import SimpleNamespace

import pytest

from bloom_lims.config import AtlasSettings
from bloom_lims.integrations.atlas.client import AtlasClient, AtlasClientError
from bloom_lims.integrations.atlas.events import AtlasEventClient


def test_atlas_settings_rejects_non_https_base_url():
    with pytest.raises(ValueError, match="absolute https:// URL"):
        AtlasSettings(base_url="http://atlas.example")


def test_atlas_client_rejects_non_https_base_url():
    with pytest.raises(AtlasClientError, match="absolute https:// URL"):
        AtlasClient(base_url="http://atlas.example", token="atlas-token")


def test_atlas_event_client_rejects_non_https_base_url():
    client = AtlasEventClient(
        SimpleNamespace(
            base_url="http://atlas.example",
            organization_id="ORG-1",
            webhook_secret="secret",
            events_enabled=True,
            events_path="/api/integrations/bloom/v1/events",
            verify_ssl=True,
            events_timeout_seconds=5,
            events_max_retries=0,
        )
    )

    with pytest.raises(ValueError, match="absolute https:// URL"):
        client._endpoint()
