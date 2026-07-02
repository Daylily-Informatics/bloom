from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from bloom_lims.app import _access_log_payload, _emit_access_log


def test_common_access_log_payload_is_json(caplog) -> None:
    request = SimpleNamespace(
        state=SimpleNamespace(
            request_id="req-1",
            correlation_id="corr-1",
            auth_mode="ai_agent_token",
            ai_agent_id="agent-1",
            authorizing_human="johnm@lsmc.com",
            denial_reason="forbidden",
        ),
        client=SimpleNamespace(host="127.0.0.1"),
        method="GET",
        url=SimpleNamespace(path="/api/v1/search"),
    )
    payload = _access_log_payload(
        request=request,
        service_id="bloom",
        status_code=403,
        duration_ms=12.34,
        route_template="/api/v1/search",
    )

    with caplog.at_level(logging.WARNING, logger="lsmc.access"):
        _emit_access_log(payload, level=logging.WARNING)

    records = [record for record in caplog.records if record.name == "lsmc.access"]
    body = json.loads(records[-1].getMessage())
    assert body["event"] == "request_completed"
    assert body["request_id"] == "req-1"
    assert body["service_id"] == "bloom"
    assert body["actor"] == "johnm@lsmc.com"
    assert body["ai_agent_id"] == "agent-1"
    assert body["authorizing_human"] == "johnm@lsmc.com"
    assert body["ip"] == "127.0.0.1"
    assert body["route_template"] == "/api/v1/search"
    assert body["status"] == 403
    assert body["duration_ms"] == 12.34
    assert body["denial_reason"] == "forbidden"
    assert body["auth_mode"] == "ai_agent_token"
