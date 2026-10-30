"""Root-operated native runtime-role preflight/apply/readback for Bloom 174.

Run with the owning service's exact TapDB package pin and tagged app source.
The only database connection is public native TAPDBConnection under Bloom's
bound runtime identity. Preflight/readback roll back; apply is one SERIALIZABLE
runtime transaction and records its commit status.
No application bootstrap, schema initialization, fallback, or broad repair.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener

from sqlalchemy import text

from daylily_tapdb import TAPDBConnection
from daylily_tapdb.cli.db_config import get_db_config
from daylily_tapdb.models.template import generic_template
from daylily_tapdb.templates.manager import TemplateManager
from daylily_tapdb.web.dag_v2 import validate_dag_v2_manifest


SPECS = {
    "bloom": {
        "tag": "10.0.12",
        "commit": "90b5f059e2cdcdf781b051198a5a5030871d8172",
        "tapdb": "10.1.4",
        "database": "tapdb_bloom_prod",
        "schema": "tapdb_bloom_lsmcok1_local",
        "runtime_user": "bloom_runtime_10",
        "domain_code": "M",
        "ssl": "true",
        "owner_repo_name": "bloom",
        "tenant_id": "",
        "additional_tenant_ids": [],
        "allow_global_claims": True,
        "module": "scripts/repair_atlas_owner_references.py",
        "count": 174,
    },
}

RUNTIME_CONFIG = Path('/home/ubuntu/.config/tapdb/bloom/bloom-day/tapdb-config.yaml')
SOURCE_DIR = Path('/home/ubuntu/bloom-10.0.12-20260927T001606Z/source')
REQUIRED_TEMPLATE_UID = 244


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _save(path: Path, payload: dict, *, exclusive: bool = False) -> None:
    data = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    if exclusive:
        with path.open("x") as output:
            output.write(data)
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(data)
    temporary.replace(path)


def _load_exact_source(source: Path, service: str, spec: dict):
    if source != SOURCE_DIR or not source.is_dir():
        raise ValueError("Exact tagged source directory is missing")
    def git(*arguments: str) -> str:
        return subprocess.check_output(
            ["git", "-c", "safe.directory=" + str(source),
             "-C", str(source), *arguments], text=True
        ).strip()
    if (git("cat-file", "-t", spec["tag"]) != "tag"
            or git("rev-parse", "HEAD") != spec["commit"]
            or git("rev-parse", spec["tag"] + "^{}") != spec["commit"]
            or git("status", "--porcelain")):
        raise ValueError("Source is not the clean exact annotated release")
    if importlib.metadata.version("daylily-tapdb") != spec["tapdb"]:
        raise ValueError("Repair must use the producer's retained native TapDB pin")
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

    def load(relative: str, suffix: str):
        path = source / relative
        if not path.is_file():
            raise ValueError(f"Tagged {service} repair module is missing")
        module_spec = importlib.util.spec_from_file_location(
            f"{service}_{suffix}_runtime", path
        )
        if module_spec is None or module_spec.loader is None:
            raise ValueError("Cannot load exact tagged repair module")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        return module

    return load(spec["module"], "repair")


def _runtime_config(path: Path, config_sha: str, spec: dict) -> dict:
    if path != RUNTIME_CONFIG or not path.is_file() or path.is_symlink():
        raise ValueError("Exact bound Bloom runtime config is required")
    if _sha(path) != config_sha:
        raise ValueError("Reviewed Bloom runtime config changed")
    cfg = get_db_config(config_path=path)
    if (cfg.get("config_path") != str(RUNTIME_CONFIG)
            or cfg.get("database") != spec["database"]
            or cfg.get("schema_name") != spec["schema"]
            or cfg.get("engine_type") != "aurora"
            or cfg.get("cluster_identifier") != "dayhoff-lsmcok1-tapdb"
            or cfg.get("region") != "us-west-2"
            or str(cfg.get("server_port")) != "5432"
            or cfg.get("ssl") != spec["ssl"]
            or cfg.get("operator_configured") is not False
            or cfg.get("user") != spec["runtime_user"]
            or cfg.get("domain_code") != spec["domain_code"]
            or cfg.get("owner_repo_name") != spec["owner_repo_name"]
            or cfg.get("tenant_id") != spec["tenant_id"]
            or cfg.get("allow_global_claims") is not spec["allow_global_claims"]
            or cfg.get("additional_tenant_ids") != spec["additional_tenant_ids"]):
        raise ValueError("Native Bloom runtime target differs from bound inventory")
    return cfg


def _context_projection(cfg: dict, actor: str) -> dict:
    return {
        "config_identity": cfg["config_path"],
        "schema_name": cfg["schema_name"],
        "domain_code": cfg["domain_code"],
        "owner_repo_name": cfg["owner_repo_name"],
        "tenant_id": cfg["tenant_id"],
        "additional_tenant_ids": cfg["additional_tenant_ids"],
        "actor": actor,
        "allow_global_rows": cfg["allow_global_claims"],
        "database_role": cfg["user"],
        "connection_role": "runtime",
        "template_uid": REQUIRED_TEMPLATE_UID,
    }


def _session(cfg: dict, actor: str, *, read_only: bool):
    """Return a context manager for one bounded public native transaction."""
    from contextlib import contextmanager

    @contextmanager
    def run():
        iam = str(cfg["iam_auth"]).strip().lower()
        if iam not in {"true", "false"}:
            raise ValueError("Explicit runtime iam_auth must be true/false")
        with TAPDBConnection(
            db_hostname=f"{cfg['host']}:{cfg['port']}",
            db_hostaddr=cfg.get("hostaddr") or None,
            db_user=cfg["user"], db_pass=cfg.get("password") or "",
            secret_arn=cfg.get("secret_arn") or None,
            db_name=cfg["database"], engine_type="aurora",
            region=cfg["region"], iam_auth=iam == "true",
            app_username=actor, domain_code=cfg["domain_code"],
            owner_repo_name=cfg["owner_repo_name"],
            schema_name=cfg["schema_name"],
            tenant_id=cfg["tenant_id"] or None,
            additional_tenant_ids=tuple(cfg["additional_tenant_ids"]),
            allow_global_rows=cfg["allow_global_claims"],
            config_identity=cfg["config_path"], connection_role="runtime",
            aws_profile=cfg.get("aws_profile") or None,
            sslrootcert=cfg.get("sslrootcert") or None,
            server_port=int(cfg["server_port"]),
        ) as connection:
            connection.engine.update_execution_options(
                isolation_level=("REPEATABLE READ" if read_only else "SERIALIZABLE"),
                postgresql_readonly=read_only,
            )
            with connection.session_scope(commit=not read_only) as session:
                session.autoflush = False
                session.execute(text("SET LOCAL statement_timeout = '60s'"))
                session.execute(text("SET LOCAL lock_timeout = '2s'"))
                actual_role = session.execute(text("SELECT current_user")).scalar_one()
                if actual_role != cfg["user"]:
                    raise RuntimeError("Bound Bloom runtime DB role differs")
                template = TemplateManager().get_template(
                    session, "reference/external_identifier/tapdb_object/2.0",
                    domain_code=cfg["domain_code"],
                )
                if (template is None or template.uid != REQUIRED_TEMPLATE_UID
                        or template.issuer_app_code != "bloom"
                        or template.instance_prefix != "XRF"
                        or session.get(generic_template, 242) is not None):
                    raise RuntimeError("Bloom-owned native XRF template not visible")
                yield session
                if not read_only:
                    session.flush()

    return run()


def _owner_lookup(rows: list[dict], base_url: str, token: str):
    parsed = urlsplit(base_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")):
        raise ValueError("Atlas DAG base URL must be an exact HTTPS origin")
    if not token or token != token.strip() or "\n" in token or "\r" in token:
        raise ValueError("Exact Atlas DAG read token is required")
    origin = base_url.rstrip("/")
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), _NoRedirect)

    def get(path: str) -> dict:
        request = Request(origin + path, headers={"Authorization": "Bearer " + token})
        try:
            with opener.open(request, timeout=10) as response:
                if response.status != 200:
                    raise RuntimeError(f"Atlas native DAG HTTP {response.status}")
                content = response.read(1_048_577)
        except HTTPError as exc:
            raise RuntimeError(f"Atlas native DAG HTTP {exc.code}") from None
        except URLError:
            raise RuntimeError("Atlas native DAG read failed") from None
        if len(content) > 1_048_576:
            raise RuntimeError("Atlas native DAG response exceeds bound")
        payload = json.loads(content)
        if not isinstance(payload, dict):
            raise ValueError("Atlas native DAG response is not an object")
        return payload

    reason = validate_dag_v2_manifest(get("/api/dag/manifest"), expected_service_id="atlas")
    if reason is not None:
        raise ValueError(f"Atlas native DAG manifest rejected: {reason.value}")
    owners = {}
    for euid in sorted({row["candidate_target_euid"] for row in rows}):
        body = get("/api/dag/v2/object/" + quote(euid, safe=""))
        if (body.get("service_id") != "atlas" or body.get("euid") != euid
                or body.get("record_type") != "instance" or "tenant_id" not in body):
            raise ValueError(f"Atlas native persisted owner differs for {euid}")
        owners[euid] = body
    projection = {
        euid: {key: body.get(key) for key in (
            "service_id", "euid", "record_type", "tenant_id",
            "category", "type", "subtype", "version",
        )}
        for euid, body in owners.items()
    }
    fingerprint = hashlib.sha256(json.dumps(
        projection, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    return owners.__getitem__, fingerprint, len(owners)


def _selection(module, receipt: dict) -> list[dict]:
    rows = module.select_inventory_rows(receipt)
    if len(rows) != SPECS["bloom"]["count"]:
        raise ValueError("Bounded repair selected unexpected cohort size")
    return rows


def _prior(path: Path, expected_sha: str, mode: str, input_sha: str,
           runtime_sha: str) -> dict:
    if _sha(path) != expected_sha:
        raise ValueError("Reviewed prior repair receipt changed")
    prior = json.loads(path.read_text())
    if (prior.get("schema") != "dayhoff.producer-bounded-repair/1"
            or prior.get("service") != "bloom" or prior.get("mode") != mode
            or prior.get("input_sha256") != input_sha
            or prior.get("source_commit") != SPECS["bloom"]["commit"]
            or prior.get("connection_role") != "runtime"
            or prior.get("runtime_config_sha256") != runtime_sha):
        raise ValueError("Prior exact repair receipt differs")
    return prior


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "apply", "readback"))
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--runtime-config-sha256", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--evidence-sha256", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--preflight-receipt", type=Path)
    parser.add_argument("--preflight-receipt-sha256")
    parser.add_argument("--apply-receipt", type=Path)
    parser.add_argument("--apply-receipt-sha256")
    parser.add_argument("--atlas-base-url")
    parser.add_argument("--actor")
    args = parser.parse_args()
    os.umask(0o077)
    spec = SPECS["bloom"]
    if os.geteuid() != 0 or os.environ.get("SUDO_USER") != "ubuntu":
        raise ValueError("Targeted sudo from ubuntu required for protected runtime config")
    if os.environ.get("BLOOM_VERSION") != spec["tag"]:
        raise ValueError("Explicit tagged Bloom version override required")
    if args.mode == "apply" and not (
            args.preflight_receipt and args.preflight_receipt_sha256):
        raise ValueError("Apply requires reviewed exact preflight receipt and SHA")
    if args.mode == "readback" and not (
            args.apply_receipt and args.apply_receipt_sha256):
        raise ValueError("Readback requires exact committed apply receipt and SHA")
    if (not isinstance(args.actor, str) or not args.actor
            or args.actor != args.actor.strip() or len(args.actor) > 128
            or any(ord(character) < 32 or ord(character) == 127 for character in args.actor)):
        raise ValueError("Every repair mode requires an explicit prepared Bloom actor")
    if not args.receipt.parent.is_dir() or args.receipt.exists():
        raise ValueError("Receipt parent must exist and receipt must be new")
    module = _load_exact_source(args.source_dir, "bloom", spec)
    cfg = _runtime_config(args.runtime_config, args.runtime_config_sha256, spec)
    context_projection = _context_projection(cfg, args.actor)
    context_sha = hashlib.sha256(json.dumps(
        context_projection, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    input_sha = _sha(args.evidence)
    if input_sha != args.evidence_sha256 or input_sha != (
            "8c1945e643d79544d14bb3cd74f812c969ca5a4d2dd0ec3f2b25900eda1cf4e6"):
        raise ValueError("Fixed Bloom 174-row evidence changed")
    rows = _selection(module, json.loads(args.evidence.read_text()))
    token = os.environ.get("ATLAS_DAG_READ_TOKEN")
    if not isinstance(token, str) or not args.atlas_base_url:
        raise ValueError("Bloom repair requires Atlas DAG URL and ATLAS_DAG_READ_TOKEN")
    owner_lookup, owner_sha, owner_count = _owner_lookup(rows, args.atlas_base_url, token)
    receipt = {
        "schema": "dayhoff.producer-bounded-repair/1",
        "service": "bloom",
        "mode": args.mode,
        "state": "started",
        "source_tag": spec["tag"],
        "source_commit": spec["commit"],
        "tapdb_version": spec["tapdb"],
        "database": spec["database"],
        "schema_name": spec["schema"],
        "input_sha256": input_sha,
        "selected": len(rows),
        "transaction_context": context_projection,
        "transaction_context_sha256": context_sha,
        "owner_projection_sha256": owner_sha,
        "owner_count": owner_count,
        "connection_role": "runtime",
        "runtime_config_sha256": args.runtime_config_sha256,
    }
    _save(args.receipt, receipt, exclusive=True)

    try:
        if args.mode in ("preflight", "apply"):
            with _session(cfg, args.actor, read_only=True) as session:
                result = module.preflight(session, rows, owner_lookup)
            if result["selected"] != spec["count"]:
                raise ValueError("Native preflight selected count differs")
            receipt["preflight"] = result
            receipt["state"] = "preflight_passed"
            _save(args.receipt, receipt)
        if args.mode == "preflight":
            receipt["state"] = "completed_read_only"
        elif args.mode == "apply":
            prior = _prior(args.preflight_receipt, args.preflight_receipt_sha256,
                           "preflight", input_sha,
                           args.runtime_config_sha256)
            if (prior.get("state") != "completed_read_only"
                    or prior.get("selected") != spec["count"]
                    or prior.get("transaction_context_sha256") != context_sha
                    or prior.get("owner_projection_sha256") != owner_sha):
                raise ValueError("Reviewed preflight cohort or owner scope changed")
            receipt["state"] = "apply_transaction_started"
            _save(args.receipt, receipt)
            with _session(cfg, args.actor, read_only=False) as session:
                provenance = json.dumps({
                    "contract": "bloom.atlas-reference-bounded-repair/1",
                    "actor": args.actor, "input_sha256": input_sha,
                    "owner_projection_sha256": owner_sha,
                }, sort_keys=True, separators=(",", ":"))
                applied = module.apply(
                    session, rows, owner_lookup,
                    deactivation_provenance=provenance,
                )
                if (applied.get("selected", applied.get("updated")) != spec["count"]):
                    raise ValueError("Native repair changed fewer rows than exact cohort")
                receipt["apply"] = applied
                receipt["state"] = "apply_outcomes_pending_commit"
                _save(args.receipt, receipt)
            receipt["state"] = "committed"
            _save(args.receipt, receipt)
            with _session(cfg, args.actor, read_only=True) as session:
                readback = module.readback(
                    session, rows, applied["outcomes"], owner_lookup)
            if readback["verified"] != spec["count"]:
                raise ValueError("Committed native repair readback is incomplete")
            receipt["readback"] = readback
            receipt["state"] = "verified"
        else:
            prior = _prior(args.apply_receipt, args.apply_receipt_sha256,
                           "apply", input_sha,
                           args.runtime_config_sha256)
            if (prior.get("state") not in (
                "committed", "committed_readback_failed", "apply_outcome_unknown",
                "verified",
            )
                    or prior.get("transaction_context_sha256") != context_sha
                    or prior.get("owner_projection_sha256") != owner_sha
                    or not isinstance(prior.get("apply"), dict)
                    or not isinstance(prior["apply"].get("outcomes"), list)
                    or len(prior["apply"]["outcomes"]) != spec["count"]):
                raise ValueError("Exact committed repair receipt differs")
            with _session(cfg, args.actor, read_only=True) as session:
                readback = module.readback(
                    session, rows, prior["apply"]["outcomes"], owner_lookup)
            if readback["verified"] != spec["count"]:
                raise ValueError("Committed native repair readback is incomplete")
            receipt["readback"] = readback
            receipt["state"] = "verified"
        _save(args.receipt, receipt)
        print(json.dumps({"service": "bloom", "mode": args.mode,
                          "state": receipt["state"], "selected": len(rows),
                          "receipt": str(args.receipt)}, sort_keys=True))
    except Exception as exc:
        receipt["failure_type"] = type(exc).__name__
        if receipt["state"] == "committed":
            receipt["state"] = "committed_readback_failed"
        elif receipt["state"] in (
            "apply_transaction_started", "apply_outcomes_pending_commit"
        ):
            receipt["state"] = "apply_outcome_unknown"
        else:
            receipt["state"] = "failed"
        _save(args.receipt, receipt)
        raise


if __name__ == "__main__":
    main()
