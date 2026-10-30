"""Start only the exact Bloom 10.0.8 image after reviewed native migration success.

Prepared for root review; not executed during preparation. Run with targeted
sudo from the designated Ubuntu EC2 shell. No build, pull, migration, grant,
service-config edit, sibling restart or automatic rollback is performed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import yaml


INSTANCE = "i-07df3a933e4839f52"
DEPLOYMENT = Path("/opt/dayhoff/deployments/day")
COMPOSE = DEPLOYMENT / "compose/docker-compose.yml"
MANIFEST = DEPLOYMENT / "container-release-manifest.json"
CONTAINER = "dayhoff-day-bloom-1"
REGISTRY = "108782052779.dkr.ecr.us-west-2.amazonaws.com/dayhoff/day/bloom"
OLD_TAG = "10.0.6"
OLD_COMMIT = "a67dee5dab4a2466f4534535b720f9560f261b6e"
OLD_IMAGE = REGISTRY + "@sha256:590a8af40c0412c5e8d24c390597be253f12ac20642429ec4e338cd0b8ff2df2"
TAG = "10.0.8"
COMMIT = "1c500a71b04f185099b9b4ec38534554e60da41a"
BRANCH = "codex/bloom-kahlo-reader-auth-20260918"
IMAGE = REGISTRY + "@sha256:320ffb3e1de15991636b22f67df9a69dc63b2e05474f0a930628f84e07087f31"
BUILD_ROOT = Path("/home/ubuntu/bloom-10.0.8-20260918T175242Z")
BUILD_RECEIPT = BUILD_ROOT / "image-receipt.json"
MIGRATION_ROOT = Path("/home/ubuntu/bloom_ops/kahlo-resolver-20260918T123300Z")
MIGRATION_STEM = "native-apply-10.1.6-20260918T183600Z"
MIGRATION_RESULT = MIGRATION_ROOT / (MIGRATION_STEM + ".json")
MIGRATION_OPERATION = MIGRATION_ROOT / (MIGRATION_STEM + "-operation.json")
MIGRATION_MAINTENANCE = MIGRATION_ROOT / (MIGRATION_STEM + "-maintenance.json")
PREFLIGHT = MIGRATION_ROOT / "native-preview-10.1.6-20260918T181750Z.json"
PREFLIGHT_SHA = "b36758e02a16b44fed1b08b5f620eb5e6683e8bdb046268709ca3d974cf6c763"
SQL_NAME = "20260918_070400_system_user_authorization_contract.sql"
SQL_SHA = "e3b7313fd91777c86d3d7393c1e461f043b077b094c6dbbd340b02b70d74baf2"
TARGET_FIELDS = ("engine_type", "host", "port", "database", "schema_name",
                 "config_identity", "domain_code", "owner_repo_name")


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def output(argv):
    return subprocess.check_output(argv, text=True).strip()


def load(path, hashes):
    require(path.is_absolute() and path.is_file() and not path.is_symlink(),
            "Required exact receipt is missing or is a symlink: " + str(path))
    raw = path.read_bytes()
    hashes[str(path)] = sha(raw)
    value = json.loads(raw)
    require(isinstance(value, dict), "Receipt must be an object: " + str(path))
    return value


def target_identity(value):
    return {key: value[key] for key in TARGET_FIELDS}


def verify_migration(reviewed_sha, hashes):
    plan = load(PREFLIGHT, hashes)
    require(hashes[str(PREFLIGHT)] == PREFLIGHT_SHA, "Reviewed native preflight changed")
    require([(row["filename"], row["sha256"]) for row in plan["pending_migrations"]]
            == [(SQL_NAME, SQL_SHA)], "Unexpected pending native migration")
    require(plan["target"]["database"] == "tapdb_bloom_prod"
            and plan["target"]["schema_name"] == "tapdb_bloom_lsmcok1_local"
            and plan["identity_inventory"]["physical_target"]["database_oid"] == 17040,
            "Native migration target differs from the reviewed Bloom database")
    operation = load(MIGRATION_OPERATION, hashes)
    require(type(operation.get("return_code")) is int and operation["return_code"] == 0
            and operation.get("result_exists") is True
            and operation.get("result_path") == str(MIGRATION_RESULT)
            and operation.get("bloom_remains_stopped_for_receipt_review") is True,
            "Native migration has no successful terminal operation receipt")
    payload = load(MIGRATION_RESULT, hashes)
    require(hashes[str(MIGRATION_RESULT)] == reviewed_sha,
            "Native migration result differs from root's reviewed SHA256")
    migration = payload["migration_result"]
    completion = payload["recovery_completion"]
    release = payload["writer_fence_release"]
    allocator = completion["allocator_result"]
    require(migration["receipt_version"] == "tapdb-migration-receipt/v1"
            and migration["status"] == "applied"
            and migration["applied_migrations"] == [SQL_NAME]
            and migration["preflight_evidence_sha256"] == plan["evidence_sha256"],
            "Native result does not apply exactly the reviewed function migration")
    postflight = migration["postflight"]
    require(postflight["pending_migrations"] == []
            and migration["postflight_evidence_sha256"] == postflight["evidence_sha256"]
            and [(row["filename"], row["asset_sha256"])
                 for row in postflight["applied_migrations"] if row["filename"] == SQL_NAME]
                == [(SQL_NAME, SQL_SHA)], "Native postflight does not confirm the exact SQL asset")
    require(completion["status"] == "committed" and completion["receipt_id"]
            and re.fullmatch(r"[0-9a-f]{64}", completion["receipt_sha256"])
            and allocator["schema_version"] == "tapdb-sequence-apply/v1"
            and allocator["phase"] == "committed",
            "Migration lacks separate committed recovery and allocator evidence")
    require(release["schema_version"] == "tapdb-writer-fence/v1"
            and release["phase"] == "released"
            and release["result_sha256"] == allocator["sha256"]
            and release["intent_receipt_id"] and isinstance(release["restored_acl"], dict),
            "Matching native writer-fence release is absent; leave Bloom stopped")
    exact_target = target_identity(plan["target"])
    for value in (migration["target"], postflight["target"], release["target"],
                  allocator["inventory"]["target"]):
        require(target_identity(value) == exact_target, "Native receipt target mismatch")
    require(release["physical_target"] == allocator["inventory"]["physical_target"]
            and release["physical_target"]["database_oid"] == 17040,
            "Writer-fence release has a different physical database")
    maintenance = load(MIGRATION_MAINTENANCE, hashes)
    require(maintenance["preflight_sha256"] == PREFLIGHT_SHA,
            "Maintenance boundary used a different preflight")
    return {"result_path": str(MIGRATION_RESULT), "result_sha256": reviewed_sha,
            "migration": SQL_NAME, "sql_sha256": SQL_SHA,
            "recovery_status": completion["status"],
            "recovery_receipt_id": completion["receipt_id"],
            "writer_fence_phase": release["phase"],
            "writer_fence_release_sha256": release["sha256"]}, maintenance


def inspect_image(reference):
    rows = json.loads(output(["docker", "image", "inspect", reference]))
    require(len(rows) == 1, "Expected exactly one local image")
    return rows[0]


def build_env(config):
    return dict(item.split("=", 1) for item in config["Env"] if item.startswith("BLOOM_BUILD_"))


def verify_image(hashes):
    receipt = load(BUILD_RECEIPT, hashes)
    expected = {"schema": "ursa-owy-kahlo.final-image/v1", "service": "bloom",
                "source_tag": TAG, "source_commit": COMMIT, "source_branch": BRANCH,
                "source_url": "https://github.com/lsmc-bio/bloom.git",
                "builder_instance": INSTANCE, "builder_region": "us-west-2",
                "image": IMAGE, "image_tag": REGISTRY + ":day-" + TAG,
                "build_root": str(BUILD_ROOT)}
    require(all(receipt.get(key) == value for key, value in expected.items())
            and receipt.get("tests_run") is False and receipt.get("deployed") is False,
            "Final image receipt differs from the exact reviewed Bloom release")
    source = BUILD_ROOT / "source"
    git = ["git", "-c", "safe.directory=" + str(source), "-C", str(source)]
    require(output(git + ["cat-file", "-t", TAG]) == "tag"
            and output(git + ["rev-parse", TAG + "^{commit}"]) == COMMIT
            and output(git + ["rev-parse", "HEAD"]) == COMMIT
            and not output(git + ["status", "--porcelain"]),
            "Exact annotated build source changed")
    image = inspect_image(IMAGE)
    labels = image["Config"]["Labels"]
    require(IMAGE in image["RepoDigests"]
            and labels.get("org.opencontainers.image.version") == TAG
            and labels.get("org.opencontainers.image.revision") == COMMIT
            and build_env(image["Config"]) == {
                "BLOOM_BUILD_VERSION": TAG, "BLOOM_BUILD_SHA": COMMIT,
                "BLOOM_BUILD_BRANCH": BRANCH}, "Local final image provenance differs")
    return image


def containers():
    names = output(["docker", "ps", "-a", "--filter",
                    "label=com.docker.compose.project=dayhoff-day", "--format", "{{.Names}}"]).splitlines()
    require(CONTAINER in names and len(names) == len(set(names)), "Project container inventory is incomplete")
    rows = json.loads(output(["docker", "inspect", *names]))
    return {row["Name"].lstrip("/"): {
        "id": row["Id"], "image": row["Image"], "configured_image": row["Config"]["Image"],
        "status": row["State"]["Status"], "restarts": row["RestartCount"],
        "health": row["State"].get("Health", {}).get("Status"),
        "started_at": row["State"]["StartedAt"],
        "build_provenance": build_env(row["Config"]) if row["Name"].lstrip("/") == CONTAINER else None,
    } for row in rows}


def sibling_snapshot(rows):
    return {name: {key: value[key] for key in (
        "id", "image", "configured_image", "status", "restarts", "started_at", "build_provenance")}
        for name, value in rows.items() if name != CONTAINER}


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def replace_exact(path, before, after):
    require(path.read_bytes() == before, "Deployment input changed before write: " + str(path))
    stat = path.stat()
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(after)
            stream.flush()
            os.fchmod(stream.fileno(), stat.st_mode & 0o777)
            os.fchown(stream.fileno(), stat.st_uid, stat.st_gid)
            os.fsync(stream.fileno())
        require(path.read_bytes() == before, "Deployment input changed while staging: " + str(path))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migration-result-sha256", required=True,
                        help="SHA256 of the actual successful native result after root's review")
    args = parser.parse_args()
    require(re.fullmatch(r"[0-9a-f]{64}", args.migration_result_sha256), "Exact reviewed result SHA256 is required")
    require(os.geteuid() == 0 and os.environ.get("SUDO_USER") == "ubuntu", "Use targeted sudo from Ubuntu")
    require(Path("/sys/devices/virtual/dmi/id/board_asset_tag").read_text().strip() == INSTANCE,
            "Unexpected deployment instance")
    os.umask(0o077)
    hashes = {}
    migration, maintenance = verify_migration(args.migration_result_sha256, hashes)
    target_image = verify_image(hashes)
    old_image = inspect_image(OLD_IMAGE)
    compose_bytes = COMPOSE.read_bytes()
    manifest_bytes = MANIFEST.read_bytes()
    compose = yaml.safe_load(compose_bytes)
    manifest = json.loads(manifest_bytes)
    require(manifest.get("deploy_name") == "day", "Manifest deployment identity differs")
    recorded = manifest["images"]["bloom"]
    require(recorded["image"] == OLD_IMAGE and recorded["source_tag"] == OLD_TAG
            and recorded["source_commit"] == OLD_COMMIT, "Manifest Bloom baseline changed")
    require(compose["services"]["bloom"]["image"] == OLD_IMAGE, "Compose Bloom baseline changed")
    environment = compose["services"]["bloom"].get("environment", {})
    require(isinstance(environment, dict)
            and not any(str(key).startswith("BLOOM_BUILD_") for key in environment),
            "Compose overrides image-owned Bloom provenance; review before deployment")
    before = containers()
    stopped = before[CONTAINER]
    prior = maintenance["containers_before"][CONTAINER]
    require(stopped["configured_image"] == OLD_IMAGE and stopped["image"] == old_image["Id"]
            and stopped["status"] == "exited" and stopped["id"] == prior["id"]
            and prior["image"] == OLD_IMAGE and stopped["restarts"] == prior["restarts"],
            "Bloom is not the exact stopped container retained for migration review")
    text = compose_bytes.decode()
    require(text.count(OLD_IMAGE) == 1, "Unexpected Bloom image reference count in Compose")
    compose_after = text.replace(OLD_IMAGE, IMAGE).encode()
    expected_compose = deepcopy(compose)
    expected_compose["services"]["bloom"]["image"] = IMAGE
    require(yaml.safe_load(compose_after) == expected_compose,
            "Proposed Compose edit changes more than the Bloom image")
    manifest_after = deepcopy(manifest)
    manifest_after["images"]["bloom"].update(image=IMAGE, source_tag=TAG, source_commit=COMMIT)
    manifest_after_bytes = (json.dumps(manifest_after, indent=2) + "\n").encode()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    evidence = DEPLOYMENT / "logs" / ("bloom-" + TAG + "-deploy-" + stamp)
    evidence.mkdir(mode=0o700)
    # Preserve original key order. Native Dayhoff reconstructs the exact selected
    # mutation with json.dumps(..., indent=2), without sort_keys.
    with (evidence / "manifest-before.json").open("xb") as stream:
        stream.write(manifest_bytes)
        stream.flush()
        os.fsync(stream.fileno())
    save(evidence / "pre-deployment.json", {
        "observed_at": now(), "containers": before, "migration": migration,
        "receipt_hashes": hashes, "compose_sha256": sha(compose_bytes),
        "manifest_sha256": sha(manifest_bytes), "previous_image": OLD_IMAGE,
        "image": IMAGE, "source_tag": TAG, "source_commit": COMMIT,
    })
    require(all(sha(Path(path).read_bytes()) == value for path, value in hashes.items()),
            "A required release or native migration receipt changed")
    require(containers() == before, "Container inventory changed before the selected cutover")
    command = ["docker", "compose", "-p", "dayhoff-day", "-f", str(COMPOSE),
               "--progress", "plain", "up", "-d", "--no-deps", "--pull", "never", "--no-build", "bloom"]
    result = {"schema": "ursa-owy-kahlo.deployment/v1", "started_at": now(), "observed_at": None,
              "service": "bloom", "source_tag": TAG, "source_commit": COMMIT,
              "previous_tag": OLD_TAG, "previous_commit": OLD_COMMIT,
              "image": IMAGE, "previous_image": OLD_IMAGE, "migration": migration,
              "build_receipt": str(BUILD_RECEIPT), "command": command,
              "roles": {}, "siblings_unchanged": False,
              "compose_before_sha256": sha(compose_bytes),
              "compose_changed": False, "manifest_changed": False,
              "availability": "PENDING", "acceptance": "PENDING", "automatic_rollback": False}
    try:
        require(MANIFEST.read_bytes() == manifest_bytes, "Manifest changed before cutover")
        replace_exact(COMPOSE, compose_bytes, compose_after)
        result["compose_changed"] = True
        replace_exact(MANIFEST, manifest_bytes, manifest_after_bytes)
        result["manifest_changed"] = True
        with (evidence / "compose-up.log").open("x") as log:
            process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        result["compose_return_code"] = process.returncode
        after = containers()
        result["containers_after"] = after
        result["observed_at"] = now()
        result["roles"] = {CONTAINER: after[CONTAINER]}
        result["siblings_unchanged"] = sibling_snapshot(before) == sibling_snapshot(after)
        require(process.returncode == 0, "Bloom-only Compose start failed; inspect retained receipt/log")
        require(result["siblings_unchanged"], "A sibling ID/image/status/restart count changed during cutover")
        require(after[CONTAINER]["configured_image"] == IMAGE
                and after[CONTAINER]["image"] == target_image["Id"]
                and after[CONTAINER]["status"] == "running"
                and after[CONTAINER]["health"] != "unhealthy"
                and after[CONTAINER]["restarts"] == 0
                and after[CONTAINER]["build_provenance"] == build_env(target_image["Config"]),
                "New Bloom container identity/state/provenance differs")
        require(COMPOSE.read_bytes() == compose_after and MANIFEST.read_bytes() == manifest_after_bytes,
                "Deployment inputs changed during cutover")
        result["status"] = "started_exact_image"
    except Exception as exc:
        result["status"] = "requires_review"
        result["error"] = str(exc)
        raise
    finally:
        result.update(completed_at=now(), compose_sha256=sha(COMPOSE.read_bytes()),
                      compose_after_sha256=sha(COMPOSE.read_bytes()),
                      manifest_sha256=sha(MANIFEST.read_bytes()))
        destination = evidence / "deployment-receipt.json"
        save(destination, result)
        print(json.dumps({"receipt": str(destination), "status": result.get("status"),
                          "availability": "PENDING", "acceptance": "PENDING"}))


if __name__ == "__main__":
    main()
