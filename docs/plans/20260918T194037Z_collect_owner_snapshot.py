#!/usr/bin/env python3
"""One public Bloom owner snapshot using the explicit configured Kahlo reader.

Run on the designated EC2 host. Only the read-only snapshot API is called.
Full owner data remain in the explicit private output directory. Stdout emits
only a compressed digest/identity projection, never credentials or source data.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import yaml

INSTANCE = "i-07df3a933e4839f52"
URSA = "dayhoff-day-ursa-1"
BLOOM = "dayhoff-day-bloom-1"
URSA_IMAGE = "108782052779.dkr.ecr.us-west-2.amazonaws.com/dayhoff/day/ursa@sha256:c745ac77021b55f49f717464676dcb06945be3d26884d35d60a44df41ea75911"
BLOOM_IMAGE = "108782052779.dkr.ecr.us-west-2.amazonaws.com/dayhoff/day/bloom@sha256:320ffb3e1de15991636b22f67df9a69dc63b2e05474f0a930628f84e07087f31"
NATIVE_PROGRAM = r'''
import json,os,sys,time
from datetime import datetime,timezone
from daylib_ursa.bloom_sequencing_client import BloomSequencingClient
request=json.load(sys.stdin)
base_url=os.environ['BLOOM_OWNER_READ_BASE_URL']
token=os.environ['BLOOM_OWNER_READ_TOKEN']
if base_url != 'https://bloom.day.lsmc.bio' or not token.startswith('blm_'):
 raise RuntimeError('Explicit configured Kahlo Bloom reader is unavailable')
client=BloomSequencingClient(base_url=base_url,token=token,
 timeout_seconds=30.0,verify_ssl=True)
started=datetime.now(timezone.utc).isoformat(); before=time.monotonic()
snapshot=client.get_owner_snapshot(object_euids=tuple(request['object_euids']),
 lineage_selectors=tuple(request['lineage_selectors']))
result={'schema':'bloom.owner-snapshot-collection/1','started_at':started,
 'completed_at':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':time.monotonic()-before,
 'method':'POST','route':'/api/v1/graph/snapshot','registration_writes':False,
 'credential_source':'configured Kahlo fleet.targets.bloom.headers.Authorization','credential_value_retained':False,
 'snapshot':snapshot}
print(json.dumps(result,sort_keys=True,ensure_ascii=False,allow_nan=False))
'''


def require(value, reason):
    if not value:
        raise RuntimeError(reason)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def write(path, value):
    with path.open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--request-sha256", required=True)
    parser.add_argument("--output-directory", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    require(os.geteuid() == 0 and os.environ.get("SUDO_USER") == "ubuntu", "Use targeted sudo from Ubuntu")
    require(Path("/sys/devices/virtual/dmi/id/board_asset_tag").read_text().strip() == INSTANCE,
            "Unexpected designated instance")
    require(args.request.is_absolute() and args.request.resolve() == args.request
            and args.request.stat().st_mode & 0o077 == 0, "Request must be explicit and private")
    raw_request = args.request.read_bytes()
    require(hashlib.sha256(raw_request).hexdigest() == args.request_sha256, "Request file changed")
    authority = json.loads(raw_request)
    request = authority["request"]
    require(authority["source_proposal_sha256"] == "b129978cfb79587ea5d6b4e8e8c7e3a51836542d8276c196620ca92dc39ee88e"
            and len(request["object_euids"]) == 112 and len(request["lineage_selectors"]) == 111,
            "Request exceeds the reviewed owner set")
    require(args.output_directory.is_absolute() and args.output_directory.resolve() == args.output_directory,
            "Output directory must be canonical and absolute")
    args.output_directory.mkdir(mode=0o700, exist_ok=False)
    rows = json.loads(subprocess.check_output(["docker", "inspect", URSA, BLOOM], text=True))
    containers = {row["Name"].lstrip("/"): row for row in rows}
    identities = {}
    for name, expected in ((URSA, URSA_IMAGE), (BLOOM, BLOOM_IMAGE)):
        row = containers[name]
        require(row["Config"]["Image"] == expected and row["State"]["Running"] is True,
                "Selected deployed image identity differs")
        identities[name] = {"id": row["Id"], "image": row["Config"]["Image"],
                            "image_id": row["Image"], "started_at": row["State"]["StartedAt"]}
    config_path = Path("/opt/dayhoff/deployments/day/state/kahlo/xdg/config/kahlo-day/kahlo-config-day.yaml")
    target = yaml.safe_load(config_path.read_text())["fleet"]["targets"]["bloom"]
    require(target["enabled"] is True and target["verify_ssl"] is True
            and target["expected_observability_service_id"] == "bloom"
            and target["base_urls"] == {"day": "https://bloom.day.lsmc.bio"},
            "Explicit configured Kahlo Bloom binding changed")
    require(set(target["headers"]) == {"Authorization"}, "Unexpected reader header contract")
    authorization = target["headers"]["Authorization"]
    require(isinstance(authorization, str) and authorization.startswith("Bearer blm_")
            and not any(c.isspace() for c in authorization[7:]), "Configured native reader is unavailable")
    child_env = dict(os.environ)
    child_env["BLOOM_OWNER_READ_TOKEN"] = authorization[7:]
    child_env["BLOOM_OWNER_READ_BASE_URL"] = target["base_urls"]["day"]
    process = subprocess.run(["docker", "exec", "-i", "--env", "BLOOM_OWNER_READ_TOKEN",
                              "--env", "BLOOM_OWNER_READ_BASE_URL", URSA,
                              "/app/.venv/bin/python", "-c", NATIVE_PROGRAM],
                             input=json.dumps(request).encode(), env=child_env,
                             capture_output=True, timeout=90)
    child_env.pop("BLOOM_OWNER_READ_TOKEN")
    write(args.output_directory / "snapshot.stdout.json", process.stdout)
    write(args.output_directory / "snapshot.stderr", process.stderr)
    require(process.returncode == 0, "Native public snapshot failed; retain private stdout/stderr")
    collection = json.loads(process.stdout)
    snapshot = collection["snapshot"]
    require(snapshot["request_sha256"] == digest(request), "Native request digest differs")
    observed_edges = {(edge["parent_euid"], edge["child_euid"], edge["relationship_type"]): edge["euid"]
                      for edge in snapshot["lineages"]}
    expected_edges = {(edge["parent_euid"], edge["child_euid"], edge["relationship_type"]): edge["euid"]
                      for edge in authority["expected_lineages"]}
    require(observed_edges == expected_edges, "Persisted lineage identity changed")
    namespace = authority["namespace"]
    summaries = []
    for row in snapshot["objects"]:
        value = row["json_addl"]
        require(isinstance(value, dict) and isinstance(value.get("properties", {}), dict),
                "Owner JSON/properties is not a mapping")
        properties = value.get("properties", {})
        summaries.append({"euid": row["euid"], "json_addl_sha256": digest(value),
                          "object_sha256": digest(row), "namespace_present": namespace in properties,
                          "namespace_sha256": digest(properties[namespace]) if namespace in properties else None})
    result = {"schema": "bloom.owner-preconditions-observation/1", "registration_writes": False,
              "source_proposal_sha256": authority["source_proposal_sha256"],
              "request_file_sha256": args.request_sha256, "request_sha256": digest(request),
              "started_at": collection["started_at"], "completed_at": collection["completed_at"],
              "observed_at": snapshot["observed_at"], "elapsed_seconds": collection["elapsed_seconds"],
              "native_snapshot_sha256": snapshot["snapshot_sha256"],
              "native_snapshot_file": str(args.output_directory / "snapshot.stdout.json"),
              "native_snapshot_file_sha256": hashlib.sha256(process.stdout).hexdigest(),
              "transaction_isolation": snapshot["transaction_isolation"], "read_only": snapshot["read_only"],
              "complete": snapshot["complete"], "objects": summaries, "lineage_count": len(observed_edges),
              "lineage_identities_unchanged": True, "deployed_containers": identities,
              "credential_value_retained": False,
              "credential_source": collection["credential_source"]}
    result["sha256"] = digest(result)
    compact = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode()
    write(args.output_directory / "preconditions-observation.json", compact)
    print(json.dumps({"schema": "bloom.private-observation-transport/1",
                      "gzip_base64": base64.b64encode(gzip.compress(compact)).decode(),
                      "observation_file_sha256": hashlib.sha256(compact).hexdigest(),
                      "private_evidence_directory": str(args.output_directory), "registration_writes": False}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "stopped", "error_class": type(exc).__name__}))
        raise SystemExit(1) from None
