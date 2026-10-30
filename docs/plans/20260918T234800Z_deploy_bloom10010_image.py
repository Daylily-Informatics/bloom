"""Cut over only running Bloom 10.0.9 to the reviewed final 10.0.10 image.

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
OLD_TAG = "10.0.9"
OLD_COMMIT = "1b8d12dbbd8e9159c4aeba2583446f2d657df5ef"
OLD_IMAGE = REGISTRY + "@sha256:8702ffe9381a8b4c971d08a30558b285e6b3afedb33f80a264020ee153bf5692"
TAG = "10.0.10"
COMMIT = "534b8136a4a8f5dbf02f886cdddef59d93e751c2"
TAG_OBJECT = "3d848c7c8ca0de324bf3708050a95f20e3c103ad"
BRANCH = "codex/bloom-kahlo-reader-auth-20260918"


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


def inspect_image(reference):
    rows = json.loads(output(["docker", "image", "inspect", reference]))
    require(len(rows) == 1, "Expected exactly one local image")
    return rows[0]


def build_env(config):
    return dict(item.split("=", 1) for item in config["Env"] if item.startswith("BLOOM_BUILD_"))


def verify_image(receipt_path, reviewed_sha, hashes):
    receipt = load(receipt_path, hashes)
    require(hashes[str(receipt_path)] == reviewed_sha, "Reviewed final build receipt changed")
    expected = {"schema": "ursa-owy-kahlo.final-image/v1", "service": "bloom",
                "source_tag": TAG, "source_commit": COMMIT, "source_branch": BRANCH,
                "source_url": "https://github.com/lsmc-bio/bloom.git",
                "builder_instance": INSTANCE, "builder_region": "us-west-2",
                "image_tag": REGISTRY + ":day-" + TAG}
    require(all(receipt.get(key) == value for key, value in expected.items())
            and receipt.get("tests_run") is False and receipt.get("deployed") is False,
            "Final image receipt differs from the exact reviewed Bloom release")
    reference = receipt["image"]
    require(re.fullmatch(re.escape(REGISTRY) + r"@sha256:[0-9a-f]{64}", reference),
            "Build receipt does not contain an exact Bloom image digest")
    root = Path(receipt["build_root"])
    require(root.is_absolute() and root.resolve() == root
            and receipt_path == root / "image-receipt.json",
            "Explicit build root/receipt identities differ")
    completed = datetime.fromisoformat(receipt["completed_at"].replace("Z", "+00:00"))
    require(completed.tzinfo is not None and completed <= datetime.now(timezone.utc),
            "Build completion timestamp is invalid or in the future")
    build_log = Path(receipt["build_log"])
    require(build_log == root / "build.log" and build_log.is_file()
            and not build_log.is_symlink()
            and sha(build_log.read_bytes()) == receipt["build_log_sha256"],
            "Final build log identity changed")
    hashes[str(build_log)] = receipt["build_log_sha256"]
    source = root / "source"
    git = ["git", "-c", "safe.directory=" + str(source), "-C", str(source)]
    require(output(git + ["cat-file", "-t", TAG]) == "tag"
            and output(git + ["rev-parse", TAG]) == TAG_OBJECT
            and output(git + ["rev-parse", TAG + "^{commit}"]) == COMMIT
            and output(git + ["rev-parse", "HEAD"]) == COMMIT
            and not output(git + ["status", "--porcelain"]),
            "Exact annotated build source changed")
    image = inspect_image(reference)
    labels = image["Config"]["Labels"]
    require(reference in image["RepoDigests"]
            and labels.get("org.opencontainers.image.version") == TAG
            and labels.get("org.opencontainers.image.revision") == COMMIT
            and build_env(image["Config"]) == {
                "BLOOM_BUILD_VERSION": TAG, "BLOOM_BUILD_SHA": COMMIT,
                "BLOOM_BUILD_BRANCH": BRANCH}, "Local final image provenance differs")
    return reference, image


def environment(config):
    items = config["Env"]
    parsed = dict(item.split("=", 1) for item in items)
    require(len(parsed) == len(items), "Ambiguous duplicate container environment keys")
    return parsed


def attachments(row):
    return sorted(({key: mount.get(key) for key in (
        "Type", "Source", "Destination", "Mode", "RW", "Propagation")}
        for mount in row["Mounts"]), key=lambda mount: (mount["Destination"], mount["Source"] or ""))


def mounted_file(container_path, row):
    """Project an explicit runtime path through the actual inspected bind map."""
    target = Path(container_path)
    require(target.is_absolute() and ".." not in target.parts,
            "Runtime config path is not explicit and absolute")
    matches = []
    for mount in row["Mounts"]:
        if mount["Type"] != "bind":
            continue
        destination = Path(mount["Destination"])
        if target == destination or destination in target.parents:
            matches.append((len(destination.parts), Path(mount["Source"]) / target.relative_to(destination)))
    require(matches, "Explicit runtime config is not available in the actual bind map")
    matches.sort(key=lambda pair: pair[0], reverse=True)
    require(len(matches) == 1 or matches[0][0] > matches[1][0], "Ambiguous runtime bind mapping")
    path = matches[0][1]
    require(path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink(),
            "Actual bound runtime config is missing or noncanonical")
    return path


def runtime_authority(row):
    env = environment(row["Config"])
    config = mounted_file(env["BLOOM_CONFIG_PATH"], row)
    config_bytes = config.read_bytes()
    configured = yaml.safe_load(config_bytes)
    paths = {str(config): sha(config_bytes)}
    for key in ("config_path", "domain_registry_path", "prefix_ownership_registry_path"):
        explicit = configured["tapdb"][key]
        override = "BLOOM_TAPDB__" + key.upper()
        require(override not in env or env[override] == explicit,
                "Runtime TapDB environment conflicts with explicit Bloom config")
        path = mounted_file(explicit, row)
        paths[str(path)] = sha(path.read_bytes())
    return {"runtime_file_hashes": paths, "mounts": attachments(row),
            "non_provenance_environment_sha256": sha(json.dumps(
                {k: v for k, v in env.items() if not k.startswith("BLOOM_BUILD_")},
                sort_keys=True, separators=(",", ":")).encode())}


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
    parser.add_argument("--build-receipt", required=True, type=Path,
                        help="Absolute actual final 10.0.10 build receipt path")
    parser.add_argument("--build-receipt-sha256", required=True,
                        help="SHA256 of that actual final build receipt after root review")
    parser.add_argument("--apply", action="store_true", required=True)
    args = parser.parse_args()
    require(re.fullmatch(r"[0-9a-f]{64}", args.build_receipt_sha256), "Exact reviewed result SHA256 is required")
    require(os.geteuid() == 0 and os.environ.get("SUDO_USER") == "ubuntu", "Use targeted sudo from Ubuntu")
    require(Path("/sys/devices/virtual/dmi/id/board_asset_tag").read_text().strip() == INSTANCE,
            "Unexpected deployment instance")
    os.umask(0o077)
    hashes = {}
    require(args.build_receipt.resolve() == args.build_receipt,
            "Build receipt path must be canonical and absolute")
    image_reference, target_image = verify_image(args.build_receipt, args.build_receipt_sha256, hashes)
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
    compose_environment = compose["services"]["bloom"].get("environment", {})
    require(isinstance(compose_environment, dict)
            and not any(str(key).startswith("BLOOM_BUILD_") for key in compose_environment),
            "Compose overrides image-owned Bloom provenance; review before deployment")
    before = containers()
    current = before[CONTAINER]
    require(current["configured_image"] == OLD_IMAGE and current["image"] == old_image["Id"]
            and current["status"] == "running" and current["health"] != "unhealthy"
            and current["build_provenance"] == {
                "BLOOM_BUILD_VERSION": OLD_TAG, "BLOOM_BUILD_SHA": OLD_COMMIT,
                "BLOOM_BUILD_BRANCH": BRANCH},
            "Bloom is not the exact running 10.0.9 baseline")
    before_native = json.loads(output(["docker", "inspect", CONTAINER]))[0]
    runtime_before = runtime_authority(before_native)
    require(before_native["Id"] == current["id"], "Bloom changed during config authority capture")
    require({k: v for k, v in environment(old_image["Config"]).items() if not k.startswith("BLOOM_BUILD_")}
            == {k: v for k, v in environment(target_image["Config"]).items() if not k.startswith("BLOOM_BUILD_")},
            "The selected image changes non-provenance environment defaults; review scope")
    text = compose_bytes.decode()
    require(text.count(OLD_IMAGE) == 1, "Unexpected Bloom image reference count in Compose")
    compose_after = text.replace(OLD_IMAGE, image_reference).encode()
    expected_compose = deepcopy(compose)
    expected_compose["services"]["bloom"]["image"] = image_reference
    require(yaml.safe_load(compose_after) == expected_compose,
            "Proposed Compose edit changes more than the Bloom image")
    manifest_after = deepcopy(manifest)
    manifest_after["images"]["bloom"].update(image=image_reference, source_tag=TAG, source_commit=COMMIT)
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
        "observed_at": now(), "containers": before, "runtime_authority": runtime_before,
        "receipt_hashes": hashes, "compose_sha256": sha(compose_bytes),
        "manifest_sha256": sha(manifest_bytes), "previous_image": OLD_IMAGE,
        "image": image_reference, "source_tag": TAG, "source_commit": COMMIT,
    })
    require(all(sha(Path(path).read_bytes()) == value for path, value in hashes.items()),
            "A required final build receipt or build log changed")
    require(containers() == before, "Container inventory changed before the selected cutover")
    require(runtime_authority(json.loads(output(["docker", "inspect", CONTAINER]))[0]) == runtime_before,
            "Runtime config/attachments changed before the selected cutover")
    command = ["docker", "compose", "-p", "dayhoff-day", "-f", str(COMPOSE),
               "--progress", "plain", "up", "-d", "--no-deps", "--pull", "never", "--no-build", "bloom"]
    result = {"schema": "ursa-owy-kahlo.deployment/v1", "started_at": now(), "observed_at": None,
              "service": "bloom", "source_tag": TAG, "source_commit": COMMIT,
              "previous_tag": OLD_TAG, "previous_commit": OLD_COMMIT,
              "image": image_reference, "previous_image": OLD_IMAGE,
              "runtime_authority_before": runtime_before, "runtime_authority_unchanged": False,
              "build_receipt": str(args.build_receipt), "build_receipt_sha256": args.build_receipt_sha256, "command": command,
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
        require(after[CONTAINER]["configured_image"] == image_reference
                and after[CONTAINER]["image"] == target_image["Id"]
                and after[CONTAINER]["status"] == "running"
                and after[CONTAINER]["health"] != "unhealthy"
                and after[CONTAINER]["restarts"] == 0
                and after[CONTAINER]["build_provenance"] == build_env(target_image["Config"]),
                "New Bloom container identity/state/provenance differs")
        runtime_after = runtime_authority(json.loads(output(["docker", "inspect", CONTAINER]))[0])
        result["runtime_authority_after"] = runtime_after
        result["runtime_authority_unchanged"] = runtime_before == runtime_after
        require(result["runtime_authority_unchanged"],
                "Bloom config, TapDB principal/config inputs, mounts or non-provenance environment changed")
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
