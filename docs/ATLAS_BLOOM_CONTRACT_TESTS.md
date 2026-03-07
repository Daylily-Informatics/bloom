# Atlas Bloom Contract Tests

This document captures executable contract expectations for Atlas -> Bloom workflows.

## Endpoint Matrix

| Workflow | Endpoint | Method | Auth | Required Headers | Expected Status |
|---|---|---|---|---|---|
| Create container | `/api/v1/object-creation/create` | `POST` | Bloom bearer token | `Authorization` | `200` |
| Patch container | `/api/v1/containers/{euid}` | `PATCH` | Bloom bearer token | `Authorization` | `200` |
| Create specimen | `/api/v1/external/specimens` | `POST` | Bloom bearer token (`blm_...`) | `Authorization`, `Idempotency-Key` | `200` |
| Get specimen | `/api/v1/external/specimens/{specimen_euid}` | `GET` | Bloom bearer token (`blm_...`) | `Authorization` | `200` |
| Update specimen | `/api/v1/external/specimens/{specimen_euid}` | `PATCH` | Bloom bearer token (`blm_...`) | `Authorization` | `200` |
| Delete specimen | `/api/v1/content/{specimen_euid}` | `DELETE` | Bloom bearer token | `Authorization` | `200` |
| Lookup by reference | `/api/v1/external/specimens/by-reference` | `GET` | Bloom bearer token (`blm_...`) | `Authorization` | `200` |
| Atlas webhook receive | `/api/integrations/bloom/v1/events` (Atlas side) | `POST` | HMAC signature | `X-Bloom-Signature`, `X-Bloom-Event-Id` | `202` |

## Pytest Patterns

```python
def test_create_container_contract(client):
    payload = {
        "category": "container",
        "type": "tube",
        "subtype": "tube-generic-10ml",
        "version": "1.0",
        "name": "atlas contract tube",
        "properties": {"name": "atlas contract tube"},
    }
    resp = client.post("/api/v1/object-creation/create", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["euid"]
```

```python
def test_specimen_crud_contract(client, container_euid):
    create_payload = {
        "specimen_template_code": "content/specimen/blood-whole/1.0",
        "container_euid": container_euid,
        "atlas_refs": {"order_number": "ORD-1", "patient_id": "PAT-1", "kit_barcode": "KIT-1"},
        "properties": {"source": "atlas"},
    }
    created = client.post(
        "/api/v1/external/specimens",
        json=create_payload,
        headers={"Idempotency-Key": "idem-1"},
    )
    assert created.status_code == 200
    specimen_euid = created.json()["specimen_euid"]

    got = client.get(f"/api/v1/external/specimens/{specimen_euid}")
    assert got.status_code == 200

    patched = client.patch(
        f"/api/v1/external/specimens/{specimen_euid}",
        json={"status": "inactive", "properties": {"qc_state": "failed"}},
    )
    assert patched.status_code == 200

    deleted = client.delete(f"/api/v1/content/{specimen_euid}")
    assert deleted.status_code == 200
```

```python
def test_lookup_by_reference_contract(client):
    resp = client.get("/api/v1/external/specimens/by-reference", params={"order_number": "ORD-1"})
    assert resp.status_code == 200
    assert "items" in resp.json()
```

```python
def test_webhook_signature_contract():
    body = b'{"organization_id":"...","event_id":"evt-1","event_type":"specimen.updated","payload":{"euid":"SP-1"}}'
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert headers["X-Bloom-Signature"] == f"sha256={expected}"
    assert headers["X-Bloom-Event-Id"] == "evt-1"
```

## Negative-Path Matrix

| Scenario | Expected Outcome |
|---|---|
| Missing `Authorization` on protected endpoint | `401` |
| Invalid token | `401` |
| Unsupported specimen template code | `400` (validation failure) |
| Missing Atlas refs for external specimen create | `400` |
| Atlas dependency unavailable during ref validation | `424` |
| Missing `Idempotency-Key` for Atlas facade create flows | rejected by integration facade (`400`) |

## Run Commands

```bash
source /Users/jmajor/projects/daylily/bloom/bloom_activate.sh
pytest --no-cov -q tests/test_atlas_workflow_contract.py
pytest --no-cov -q tests/test_atlas_lookup_resilience.py
```
