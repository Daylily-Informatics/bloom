#!/usr/bin/env python3
"""Prepare or execute the reviewed campaign's conditional Bloom PATCH operations.

Preparation is offline. Resolution reads the real ONT creation receipt and native
snapshot. Apply is explicit, holds the shared campaign writer lock, preserves
the original journal, and calls only conditional PATCH plus public read APIs.
All payloads and receipts belong in the private campaign directory, never Git.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

PROPOSAL_SHA = "b129978cfb79587ea5d6b4e8e8c7e3a51836542d8276c196620ca92dc39ee88e"
NAMESPACE = "dayoa_campaign_20260918"
BASE_URL = "https://bloom.day.lsmc.bio"
ONT_ALIAS = "ont_current_sequencing_run"
ONT_CREATE_ID = "op-cbe0f7385b8ead9ee0342546"
SEED_JOURNAL_SHA = "469d007a34b36281b728c004c2aac67fee2e50ee56238dc8184d23f8ebbb8aea"


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path, expected=None):
    require(path.is_absolute() and path.resolve() == path and path.is_file()
            and path.stat().st_mode & 0o077 == 0, "Private canonical file required")
    require(expected is None or file_sha(path) == expected, "Input file digest differs")
    return json.loads(path.read_bytes())


def save(path, value):
    require(path.is_absolute() and path.resolve() == path, "Canonical output path required")
    with path.open("xb") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                                allow_nan=False).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def exact_euid(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+)+", value),
            "Exact persisted owner identity required")
    return value


def journal_path(campaign):
    path = campaign / "operation_journal.jsonl"
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    require(len(lines) >= 117 and hashlib.sha256(b"".join(lines[:117])).hexdigest()
            == SEED_JOURNAL_SHA, "Original 117-row journal seed changed")
    return path


def append_journal(path, operation, event, status, **fields):
    row = {"schema": "owy.owner-registration-journal/1", "at": now(),
           "operation_id": operation["operation_id"], "alias": operation["alias"],
           "request_declaration_sha256": operation["request_declaration_sha256"],
           "event": event, "status": status, "request_sent": False,
           "owner_receipt": None, **fields}
    with path.open("ab") as stream:
        stream.write(canonical(row) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Owner API redirect is not authorized")


def request(method, route, body=None):
    require(method in {"GET", "POST", "PATCH"} and route.startswith("/")
            and "?" not in route and ".." not in route, "Unexpected public API request")
    token = os.environ.get("OWY_BLOOM_API_TOKEN", "")
    require(token.startswith("blm_") and not any(c.isspace() for c in token),
            "Existing OWY_BLOOM_API_TOKEN required")
    req = urllib.request.Request(BASE_URL + route, data=None if body is None else canonical(body),
                                 method=method, headers={"Authorization": "Bearer " + token,
                                                        "Content-Type": "application/json",
                                                        "Accept": "application/json"})
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(req, timeout=30) as response:
            raw = response.read(32 * 1024 * 1024 + 1)
            require(len(raw) <= 32 * 1024 * 1024, "Native response exceeds explicit bound")
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        # Error bodies can contain private owner data; callers retain them privately.
        raw = exc.read(1024 * 1024)
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            body = {"unparsed_body_sha256": hashlib.sha256(raw).hexdigest()}
        return exc.code, body


def snapshot(objects, selectors):
    payload = {"object_euids": sorted(objects),
               "lineage_selectors": sorted(selectors, key=lambda v:
                    (v["parent_euid"], v["child_euid"], v["relationship_type"]))}
    require(1 <= len(objects) <= 128 and len(set(objects)) == len(objects)
            and len(selectors) <= 128, "Snapshot exceeds native contract bounds")
    code, body = request("POST", "/api/v1/graph/snapshot", payload)
    require(code == 200, "Native read-only owner snapshot failed")
    require(body["schema"] == "bloom.owner_snapshot/1" and body["read_only"] is True
            and body["complete"] is True and body["transaction_isolation"] == "repeatable read"
            and body["request_sha256"] == sha(payload)
            and body["snapshot_sha256"] == sha({k: v for k, v in body.items() if k != "snapshot_sha256"}),
            "Native snapshot integrity contract failed")
    require(len(body["objects"]) == len(objects)
            and {row["euid"] for row in body["objects"]} == set(objects)
            and all(row["is_deleted"] is False for row in body["objects"]),
            "Native live owner set differs")
    triples = lambda rows: {(v["parent_euid"], v["child_euid"], v["relationship_type"]) for v in rows}
    require(len(body["lineages"]) == len(selectors)
            and triples(body["lineages"]) == triples(selectors)
            and all(v["is_deleted"] is False for v in body["lineages"]),
            "Native live lineage set differs")
    return body


def proposal(campaign):
    value = load(campaign / "proposal.json", PROPOSAL_SHA)
    require(len(value["operation_order"]) == 117, "Unexpected proposal operation count")
    return value


def entry(operation, observed, euid):
    exact_euid(euid)
    value = operation["body"]["value"]
    require(len(canonical(value)) <= 65536, "Namespace exceeds native size bound")
    require(not observed["namespace_present"] or observed["namespace_sha256"] == sha(value),
            "Existing campaign namespace conflicts; overwrite is forbidden")
    route = "/api/v1/objects/" + euid + "/properties/" + NAMESPACE
    body = {"expected_json_addl_sha256": observed["json_addl_sha256"], "value": value}
    return {"operation_id": operation["operation_id"], "alias": operation["alias"],
            "request_declaration_sha256": operation["request_declaration_sha256"],
            "state": "READY", "euid": euid, "route": route, "body": body,
            "value_sha256": sha(value), "request_sha256": sha({"method": "PATCH", "route": route, "body": body}),
            "namespace_present_at_observation": observed["namespace_present"]}


def prepare(args, source):
    observed = load(args.observation, args.observation_sha256)
    require(observed["schema"] == "bloom.owner-preconditions-observation/1"
            and observed["source_proposal_sha256"] == PROPOSAL_SHA
            and observed["read_only"] is True and observed["complete"] is True
            and observed["registration_writes"] is False
            and observed["sha256"] == sha({k: v for k, v in observed.items() if k != "sha256"}),
            "Fresh observation authority differs")
    authority = load(args.snapshot_request, args.snapshot_request_sha256)
    rows = {row["euid"]: row for row in observed["objects"]}
    entries = []
    for op in source["operation_order"]:
        if op["method"] != "PATCH":
            continue
        require(op["service"] == "bloom" and op["body"]["expected_json_addl_sha256"] is None,
                "Unexpected PATCH declaration")
        euid = op["route"].split("/")[4]
        if euid == "receipt:" + ONT_ALIAS + ":euid":
            entries.append({"operation_id": op["operation_id"], "alias": op["alias"],
                            "request_declaration_sha256": op["request_declaration_sha256"],
                            "state": "DEFERRED_NATIVE_ONT_OWNER_RECEIPT", "euid": None})
        else:
            entries.append(entry(op, rows[euid], euid))
    require(len(entries) == 106 and sum(v["state"] == "READY" for v in entries) == 105,
            "Unexpected persisted/deferred owner count")
    plan = {"schema": "owy.owner-namespace-execution-plan/1", "created_at": now(),
            "source_proposal_sha256": PROPOSAL_SHA, "observation_file_sha256": args.observation_sha256,
            "native_snapshot_sha256": observed["native_snapshot_sha256"],
            "observed_at": observed["observed_at"], "mutation_performed": False,
            "namespace": NAMESPACE, "read_snapshot_request": authority["request"],
            "expected_lineages": authority["expected_lineages"], "operations": entries,
            "separate_post_operations": [v["operation_id"] for v in source["operation_order"] if v["method"] == "POST"]}
    save(args.output, plan)
    return {"status": "PREPARED", "ready": 105, "deferred": 1, "plan_sha256": file_sha(args.output)}


def resolve_ont(args, source, plan):
    aliases = load(args.campaign_directory / "aliases.json", args.aliases_sha256)
    require(aliases["schema"] == "owy.owner-registration-aliases/1"
            and aliases["proposal_sha256"] == PROPOSAL_SHA, "Native alias authority differs")
    alias = aliases["aliases"][ONT_ALIAS]
    require(alias["service"] == "bloom" and alias["operation_id"] == ONT_CREATE_ID,
            "Alias is not the authorized native ONT creation")
    owner = exact_euid(alias["euid"])
    receipt = load(Path(alias["receipt_path"]), alias["receipt_sha256"])
    create = next(v for v in source["operation_order"] if v["operation_id"] == ONT_CREATE_ID)
    require(alias["receipt_kind"] in {"native_create", "native_owner_read"},
            "Explicit native alias receipt kind is required")
    request_wire = json.dumps(create["body"], sort_keys=True, separators=(",", ":"),
                              ensure_ascii=True, allow_nan=False).encode()
    require(alias["request_sha256"] == hashlib.sha256(request_wire).hexdigest(),
            "ONT alias request body differs from the reviewed declaration")
    require(receipt["euid"] == owner
            and all(receipt[k] == create["body"][k] for k in ("type", "subtype", "name")),
            "Native ONT owner receipt identity differs from the exact proposed owner")
    if alias["receipt_kind"] == "native_create":
        require(set(receipt) == {"euid", "name", "category", "type", "subtype", "message", "created_euids"}
                and receipt["created_euids"] == [owner]
                and receipt["category"] == create["body"]["category"],
                "Native ONT creation receipt does not prove exactly one proposed owner")
    else:
        require(set(receipt) == {"euid", "name", "type", "subtype", "status", "json_addl", "created_at"}
                and isinstance(receipt["json_addl"], dict)
                and isinstance(receipt["json_addl"].get("properties"), dict)
                and all(receipt["json_addl"]["properties"].get(k) == v
                        for k, v in create["body"]["properties"].items()),
                "Native owner-read receipt does not prove the exact requested source identity")
    current = snapshot([owner], [])
    row = current["objects"][0]
    properties = row["json_addl"]["properties"]
    require(all(properties.get(k) == v for k, v in create["body"]["properties"].items())
            and row["type"] == create["body"]["type"] and row["subtype"] == create["body"]["subtype"]
            and row["name"] == create["body"]["name"],
            "Persisted ONT owner source identity differs")
    save(args.output.with_name(args.output.stem + ".ont-owner-snapshot.json"), current)
    observed = {"json_addl_sha256": sha(row["json_addl"]), "namespace_present": NAMESPACE in properties,
                "namespace_sha256": sha(properties[NAMESPACE]) if NAMESPACE in properties else None}
    deferred = [v for v in plan["operations"] if v["state"] != "READY"]
    require(len(deferred) == 1 and deferred[0]["state"] == "DEFERRED_NATIVE_ONT_OWNER_RECEIPT",
            "Unexpected deferred owner set")
    operation = next(v for v in source["operation_order"] if v["operation_id"] == deferred[0]["operation_id"])
    resolved = entry(operation, observed, owner)
    plan["operations"] = [resolved if v["operation_id"] == resolved["operation_id"] else v for v in plan["operations"]]
    plan["parent_plan_sha256"] = args.reviewed_plan_sha256
    plan["ont_resolution"] = {"aliases_file_sha256": args.aliases_sha256,
                              "native_snapshot_sha256": current["snapshot_sha256"],
                              "observed_at": current["observed_at"], **alias}
    plan["created_at"] = now()
    save(args.output, plan)
    return {"status": "PREPARED", "ready": 106, "deferred": 0, "plan_sha256": file_sha(args.output)}


def apply(args, source, plan, journal):
    code, readiness = request("GET", "/readyz")
    require(code == 200 and readiness["service"] == "bloom" and readiness["ready"] is True
            and readiness["build"]["version"] == args.expected_bloom_version
            and readiness["build"]["sha"] == args.expected_bloom_commit,
            "Explicit deployed Bloom identity/readiness differs")
    code, identity = request("GET", "/api/v1/auth/me")
    require(code == 200 and {"bloom:read", "bloom:write"} <= set(identity["permissions"]),
            "Configured owner writer lacks native permissions")
    require(bool(args.all_ready) != bool(args.operation_id), "Choose all ready operations or exact operation IDs")
    selected = [v for v in plan["operations"] if v["state"] == "READY"
                and (args.all_ready or v["operation_id"] in args.operation_id)]
    require(selected and (args.all_ready or {v["operation_id"] for v in selected} == set(args.operation_id)),
            "Selection includes unknown/deferred operations")
    require(args.evidence_directory.is_absolute() and args.evidence_directory.resolve() == args.evidence_directory,
            "Canonical absolute private evidence directory required")
    args.evidence_directory.mkdir(mode=0o700, exist_ok=False)
    save(args.evidence_directory / "readiness.json", readiness)
    declarations = {v["operation_id"]: v for v in source["operation_order"]}
    prior = [json.loads(line) for line in journal.read_text().splitlines()]
    touched = {v["operation_id"] for v in prior if v["event"] != "PREPARED_NOT_EXECUTED"
               and v["operation_id"] in {op["operation_id"] for op in selected}}
    require(not touched, "Selected PATCH already has execution history; reconcile it before a separately reviewed recovery")
    request_set = plan["read_snapshot_request"]
    owners = sorted(set(request_set["object_euids"]) | {v["euid"] for v in selected})
    before = snapshot(owners, request_set["lineage_selectors"])
    save(args.evidence_directory / "before-owner-snapshot.json", before)
    edges = lambda rows: {(v["parent_euid"], v["child_euid"], v["relationship_type"]): v["euid"] for v in rows}
    require(edges(before["lineages"]) == edges(plan["expected_lineages"]), "Existing lineage identities changed")
    before_by_id = {v["euid"]: v["json_addl"] for v in before["objects"]}
    for operation in selected:
        declaration = declarations[operation["operation_id"]]
        declared_route = declaration["route"]
        if "receipt:" in declared_route:
            require(declared_route == "/api/v1/objects/receipt:" + ONT_ALIAS + ":euid/properties/" + NAMESPACE
                    and plan["ont_resolution"]["euid"] == operation["euid"],
                    "Resolved owner is not the native ONT receipt identity")
        else:
            require(operation["route"] == declared_route, "Persisted owner target changed")
        require(declaration["method"] == "PATCH" and declaration["service"] == "bloom"
                and operation["body"]["value"] == declaration["body"]["value"]
                and operation["request_declaration_sha256"] == declaration["request_declaration_sha256"]
                and operation["route"] == "/api/v1/objects/" + exact_euid(operation["euid"]) + "/properties/" + NAMESPACE
                and operation["request_sha256"] == sha({"method": "PATCH", "route": operation["route"], "body": operation["body"]}),
                "Materialized request differs from the reviewed declaration")
        current = before_by_id[operation["euid"]]
        properties = current.get("properties", {})
        require(isinstance(properties, dict), "Owner properties are not a mapping")
        if NAMESPACE in properties:
            require(sha(properties[NAMESPACE]) == operation["value_sha256"], "Existing namespace conflicts")
        else:
            require(sha(current) == operation["body"]["expected_json_addl_sha256"],
                    "Owner changed since reviewed precondition; do not silently rebase")
    accepted = []
    for operation in selected:
        prefix = args.evidence_directory / operation["operation_id"]
        save(prefix.with_suffix(".request.json"), {"method": "PATCH", "route": operation["route"], "body": operation["body"]})
        append_journal(journal, operation, "PATCH_SEND_INTENT", "IN_PROGRESS",
                       request_sha256=operation["request_sha256"], evidence_directory=str(args.evidence_directory),
                       reviewed_plan_sha256=args.reviewed_plan_sha256)
        http_code = None
        try:
            code, receipt = request("PATCH", operation["route"], operation["body"])
            http_code = code
            receipt_path = prefix.with_suffix(".receipt.json")
            save(receipt_path, receipt)
            append_journal(journal, operation, "HTTP_RESULT", "IN_PROGRESS", request_sent=True,
                           http_status=code, request_sha256=operation["request_sha256"],
                           owner_receipt=str(receipt_path), receipt_sha256=file_sha(receipt_path))
            require(code == 200, "Native conditional PATCH did not return success")
            require(receipt["schema"] == "bloom.property_namespace_write/1"
                    and receipt["receipt_sha256"] == sha({k: v for k, v in receipt.items() if k != "receipt_sha256"})
                    and receipt["euid"] == operation["euid"] and receipt["namespace"] == NAMESPACE
                    and receipt["expected_json_addl_sha256"] == operation["body"]["expected_json_addl_sha256"]
                    and receipt["value_sha256"] == operation["value_sha256"]
                    and receipt["outcome"] in {"created", "already_present"}
                    and receipt["changed"] is (receipt["outcome"] == "created"),
                    "Native PATCH receipt integrity/identity differs")
            expected_after = copy.deepcopy(before_by_id[operation["euid"]])
            expected_after.setdefault("properties", {})[NAMESPACE] = operation["body"]["value"]
            require(receipt["before_json_addl_sha256"] == sha(before_by_id[operation["euid"]])
                    and receipt["after_json_addl_sha256"] == sha(expected_after),
                    "Native PATCH receipt changed unrelated owner content")
            after = snapshot([operation["euid"]], [])
            save(prefix.with_suffix(".readback.json"), after)
            require(after["objects"][0]["json_addl"] == expected_after,
                    "Native owner readback differs; retain committed-write evidence")
            append_journal(journal, operation, "PATCH_ACCEPTED", "SUCCESS", request_sent=True,
                           request_sha256=operation["request_sha256"], owner_receipt=str(receipt_path),
                           receipt_sha256=file_sha(receipt_path), readback_snapshot_sha256=after["snapshot_sha256"],
                           evidence_directory=str(args.evidence_directory))
            accepted.append(operation["operation_id"])
        except Exception as exc:
            rejected = http_code in {400, 401, 403, 404, 409, 422}
            append_journal(journal, operation, "PATCH_REJECTED" if rejected else "PATCH_OUTCOME_UNKNOWN",
                           "BLOCKED", request_sent=True, http_status=http_code,
                           request_sha256=operation["request_sha256"], error_class=type(exc).__name__,
                           evidence_directory=str(args.evidence_directory),
                           terminal_note="No resend. Reconcile the exact native owner/receipt before a separately reviewed recovery.")
            raise RuntimeError("PATCH phase stopped; inspect private evidence and reconcile, do not blindly resend") from None
    result = {"status": "SUCCESS", "accepted": len(accepted), "operations": accepted,
              "source_proposal_sha256": PROPOSAL_SHA, "reviewed_plan_sha256": args.reviewed_plan_sha256,
              "completed_at": now(), "registration_writes": True,
              "owner_creation_or_registration_posts_sent": 0}
    save(args.evidence_directory / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-directory", required=True, type=Path)
    sub = parser.add_subparsers(dest="mode", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--observation", required=True, type=Path)
    prep.add_argument("--observation-sha256", required=True)
    prep.add_argument("--snapshot-request", required=True, type=Path)
    prep.add_argument("--snapshot-request-sha256", required=True)
    prep.add_argument("--output", required=True, type=Path)
    resolve = sub.add_parser("resolve-ont")
    execute = sub.add_parser("apply")
    for p in (resolve, execute):
        p.add_argument("--plan", required=True, type=Path)
        p.add_argument("--reviewed-plan-sha256", required=True)
    resolve.add_argument("--aliases-sha256", required=True)
    resolve.add_argument("--output", required=True, type=Path)
    execute.add_argument("--expected-bloom-version", required=True)
    execute.add_argument("--expected-bloom-commit", required=True)
    execute.add_argument("--evidence-directory", required=True, type=Path)
    execute.add_argument("--all-ready", action="store_true")
    execute.add_argument("--operation-id", action="append", default=[])
    args = parser.parse_args()
    os.umask(0o077)
    directory = args.campaign_directory
    require(directory.is_absolute() and directory.resolve() == directory and directory.is_dir()
            and directory.stat().st_mode & 0o077 == 0, "Canonical private campaign directory required")
    with (directory / ".owner-writer.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        source = proposal(directory)
        journal = journal_path(directory)
        if args.mode == "prepare":
            result = prepare(args, source)
        else:
            plan = load(args.plan, args.reviewed_plan_sha256)
            require(plan["schema"] == "owy.owner-namespace-execution-plan/1"
                    and plan["source_proposal_sha256"] == PROPOSAL_SHA
                    and plan["namespace"] == NAMESPACE, "Execution plan authority differs")
            result = resolve_ont(args, source, plan) if args.mode == "resolve-ont" else apply(args, source, plan, journal)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not emit token-bearing exception strings or private owner payloads.
        print(json.dumps({"status": "STOPPED", "error_class": type(exc).__name__,
                          "reason": str(exc) if type(exc) is RuntimeError else "Inspect the exact private inputs and native contract"}))
        raise SystemExit(1) from None
