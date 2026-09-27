#!/usr/bin/env python3
"""Guarded Bloom-only 10.0.11 -> 10.0.12 selected cutover on the EC2 host.

Root runs plan, stop, and deploy separately. Native 174-row repair is performed
by its existing public operator runner between stop and deploy. This helper
does not repair data, build an image, or operate another Compose service.
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
import stat
import subprocess
import tempfile

import yaml


ROOT = Path('/opt/dayhoff/deployments/day')
COMPOSE = ROOT / 'compose/docker-compose.yml'
MANIFEST = ROOT / 'container-release-manifest.json'
CONFIG = Path('/home/ubuntu/.config/bloom-day/bloom-config-day.yaml')
STAGE = Path('/home/ubuntu/atlas-globaldag-20260926-operator/dag-credentials')
CONTAINER = 'dayhoff-day-bloom-1'
OLD_TAG = '10.0.11'
OLD_COMMIT = 'e29b6d6d8baf60e5cd9da5b82c74c86c0cd65953'
OLD_IMAGE = ('108782052779.dkr.ecr.us-west-2.amazonaws.com/dayhoff/day/bloom'
             '@sha256:99b2b16e54a018df748599bc9ebe0e8f1f587ee2c96b3cfb2ff72a92e46a0a4e')
TAG = '10.0.12'
COMMIT = '90b5f059e2cdcdf781b051198a5a5030871d8172'
IMAGE = ('108782052779.dkr.ecr.us-west-2.amazonaws.com/dayhoff/day/bloom'
         '@sha256:196d2f3a524da24b00a8edb89e2bbaf6c156e1e1f681459befd881819ae48606')
INSTANCE = 'i-07df3a933e4839f52'
DATABASE = 'tapdb_bloom_prod'
SCHEMA = 'tapdb_bloom_lsmcok1_local'
EVIDENCE_SHA = '8c1945e643d79544d14bb3cd74f812c969ca5a4d2dd0ec3f2b25900eda1cf4e6'


def need(ok: bool, why: str) -> None:
    if not ok:
        raise RuntimeError(why)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read(path: Path, *, private: bool = False) -> bytes:
    need(path.is_absolute() and path.resolve() == path and path.is_file()
         and not path.is_symlink() and stat.S_ISREG(path.stat().st_mode),
         'explicit regular file required')
    if private:
        need(path.stat().st_mode & 0o077 == 0, 'private input must be mode 0600')
    return path.read_bytes()


def checked(path: Path, expected: str, *, private: bool = False) -> bytes:
    need(re.fullmatch(r'[0-9a-f]{64}', expected) is not None,
         'reviewed SHA256 required')
    raw = read(path, private=private)
    need(digest(raw) == expected, 'reviewed input changed: ' + str(path))
    return raw


def object_file(path: Path, *, private: bool = False) -> dict:
    value = json.loads(read(path, private=private))
    need(isinstance(value, dict), 'JSON object required')
    return value


def receipt(path: Path, value: dict) -> None:
    need(path.is_absolute() and path.parent.is_dir() and not path.exists()
         and not path.is_symlink() and path.parent.stat().st_mode & 0o077 == 0,
         'new receipt path under mode 0700 directory required')
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def output(argv: list[str]) -> str:
    result = subprocess.run(argv, check=False, capture_output=True, text=True)
    need(result.returncode == 0, 'selected Docker inspection/operation failed')
    return result.stdout


def inventory() -> dict:
    ids = output(['docker', 'ps', '-aq', '--filter',
                  'label=com.docker.compose.project=dayhoff-day']).split()
    need(bool(ids), 'Dayhoff container inventory missing')
    rows = json.loads(output(['docker', 'inspect', *ids]))
    found = {}
    for row in rows:
        name = row['Name'].lstrip('/')
        need(name not in found, 'duplicate container name')
        found[name] = {
            'id': row['Id'], 'image_id': row['Image'],
            'configured_image': row['Config']['Image'],
            'service': row['Config']['Labels'].get('com.docker.compose.service'),
            'status': row['State']['Status'], 'exit_code': row['State']['ExitCode'],
            'oom_killed': row['State']['OOMKilled'],
            'started_at': row['State']['StartedAt'],
            'restarts': row['RestartCount'],
            'health': row['State'].get('Health', {}).get('Status'),
        }
    need(CONTAINER in found and found[CONTAINER]['service'] == 'bloom',
         'selected Bloom container missing')
    return found


def same_siblings(before: dict, after: dict) -> bool:
    keys = ('id', 'image_id', 'configured_image', 'service', 'status',
            'started_at', 'restarts', 'oom_killed')
    return set(before) == set(after) and all(
        all(before[name][key] == after[name][key] for key in keys)
        for name in before if name != CONTAINER)


def image(ref: str) -> dict:
    rows = json.loads(output(['docker', 'image', 'inspect', ref]))
    need(len(rows) == 1 and ref in rows[0].get('RepoDigests', []),
         'exact local image digest absent')
    return rows[0]


def runtime_binding() -> None:
    row = json.loads(output(['docker', 'inspect', CONTAINER]))[0]
    env_items = row['Config']['Env']
    env = dict(item.split('=', 1) for item in env_items)
    need(len(env) == len(env_items)
         and env.get('BLOOM_CONFIG_PATH') == str(CONFIG),
         'Bloom explicit runtime config path differs')
    matches = []
    for mount in row['Mounts']:
        if mount['Type'] != 'bind':
            continue
        target = Path(mount['Destination'])
        if CONFIG == target or target in CONFIG.parents:
            projected = Path(mount['Source']) / CONFIG.relative_to(target)
            matches.append((len(target.parts), projected))
    matches.sort(reverse=True)
    need(matches and (len(matches) == 1 or matches[0][0] > matches[1][0])
         and matches[0][1] == CONFIG, 'Bloom selected config bind differs')


def candidate_changes(args: argparse.Namespace) -> bytes:
    before = yaml.safe_load(checked(CONFIG, args.config_sha256))
    after = yaml.safe_load(checked(args.config_candidate,
                                   args.config_candidate_sha256, private=True))
    need(isinstance(before, dict) and isinstance(after, dict),
         'Bloom YAML mapping required')
    untouched = deepcopy(after)
    api = untouched.pop('api', None)
    atlas = untouched.pop('atlas', None)
    need(untouched == before and 'api' not in before and 'atlas' not in before,
         'Bloom config changed outside new native reader and Atlas sections')
    need(isinstance(api, dict) and set(api) ==
         {'dag_read_token_sha256', 'dag_read_actor'}
         and isinstance(api['dag_read_actor'], str)
         and bool(api['dag_read_actor'].strip())
         and len(api['dag_read_actor']) <= 128,
         'Bloom DAG reader fingerprint/actor differs')
    need(isinstance(atlas, dict) and set(atlas) == {'base_url', 'dag_read_token'}
         and atlas['base_url'] == 'https://atlas.day.lsmc.bio',
         'Bloom exact Atlas reader configuration differs')
    bloom_token = checked(STAGE / 'bloom.token', args.bloom_token_sha256,
                          private=True).decode('ascii')
    atlas_token = checked(STAGE / 'atlas.token', args.atlas_token_sha256,
                          private=True).decode('ascii')
    need(bloom_token and atlas_token and not any(c.isspace() for c in bloom_token + atlas_token)
         and api['dag_read_token_sha256'] == digest(bloom_token.encode())
         and atlas['dag_read_token'] == atlas_token,
         'staged Bloom/Atlas reader credentials do not match candidate')
    c0 = yaml.safe_load(checked(COMPOSE, args.compose_sha256))
    c1 = yaml.safe_load(checked(args.compose_candidate,
                                 args.compose_candidate_sha256, private=True))
    need(isinstance(c0, dict) and isinstance(c1, dict)
         and c0.get('name') == c1.get('name')
         and c0.get('services', {}).keys() == c1.get('services', {}).keys(),
         'Compose project/service set changed')
    old, new = c0['services']['bloom'], c1['services']['bloom']
    need(old.get('image') == OLD_IMAGE and new.get('image') == IMAGE,
         'Bloom image selection differs')
    c0_without, c1_without = deepcopy(c0), deepcopy(c1)
    c0_without['services']['bloom'].pop('image')
    c1_without['services']['bloom'].pop('image')
    need(c0_without == c1_without,
         'Compose change exceeds selected Bloom image')
    env = old.get('environment', {})
    need(isinstance(env, dict) and not any(
         str(key).startswith('BLOOM_BUILD_') for key in env),
         'Compose overrides image-owned Bloom provenance')
    manifest = json.loads(checked(MANIFEST, args.manifest_sha256))
    selected = manifest.get('images', {}).get('bloom')
    need(manifest.get('deploy_name') == 'day' and isinstance(selected, dict)
         and selected.get('image') == OLD_IMAGE
         and selected.get('source_tag') == OLD_TAG
         and selected.get('source_commit') == OLD_COMMIT,
         'Bloom release manifest baseline changed')
    next_manifest = deepcopy(manifest)
    next_manifest['images']['bloom'].update(image=IMAGE, source_tag=TAG,
                                            source_commit=COMMIT)
    return (json.dumps(next_manifest, indent=2) + '\n').encode()


def replace_exact(path: Path, old_sha: str, replacement: bytes) -> None:
    need(digest(read(path)) == old_sha, 'live file changed before replacement')
    meta = path.stat()
    fd, name = tempfile.mkstemp(prefix='.bloom10012-', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), stat.S_IMODE(meta.st_mode))
            os.fchown(stream.fileno(), meta.st_uid, meta.st_gid)
            stream.write(replacement)
            stream.flush()
            os.fsync(stream.fileno())
        need(digest(read(path)) == old_sha, 'live file changed during staging')
        os.replace(temp, path)
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        temp.unlink(missing_ok=True)


def operator_host() -> None:
    need(os.geteuid() == 0 and os.environ.get('SUDO_USER') == 'ubuntu',
         'targeted sudo from ubuntu required')
    need(read(Path('/sys/devices/virtual/dmi/id/board_asset_tag')).decode().strip()
         == INSTANCE, 'wrong EC2 instance')


def baseline(args: argparse.Namespace) -> dict:
    need(re.fullmatch(r'[0-9a-f]{64}', args.old_container_id) is not None,
         'fresh predecessor container ID required')
    candidate_changes(args)
    build = json.loads(checked(args.build_receipt,
                               args.build_receipt_sha256))
    need(build.get('schema') == 'ursa-owy-kahlo.final-image/v1'
         and build.get('service') == 'bloom'
         and build.get('source_tag') == TAG
         and build.get('source_commit') == COMMIT
         and build.get('image') == IMAGE
         and build.get('builder_instance') == INSTANCE
         and build.get('builder_region') == 'us-west-2'
         and build.get('tests_run') is False,
         'published Bloom build receipt differs')
    old_img, new_img = image(OLD_IMAGE), image(IMAGE)
    need(new_img['Config']['Labels'].get('org.opencontainers.image.version') == TAG
         and new_img['Config']['Labels'].get('org.opencontainers.image.revision') == COMMIT,
         'published Bloom image OCI identity differs')
    all_containers = inventory()
    old = all_containers[CONTAINER]
    need(old['id'] == args.old_container_id
         and old['configured_image'] == OLD_IMAGE
         and old['image_id'] == old_img['Id']
         and old['status'] == 'running'
         and old['health'] != 'unhealthy',
         'running Bloom predecessor differs')
    runtime_binding()
    return all_containers


def plan(args: argparse.Namespace) -> None:
    before = baseline(args)
    value = {
        'schema': 'bloom.selected-cutover-plan/1', 'service': 'bloom',
        'old_tag': OLD_TAG, 'old_commit': OLD_COMMIT, 'old_image': OLD_IMAGE,
        'old_container_id': args.old_container_id,
        'source_tag': TAG, 'source_commit': COMMIT, 'image': IMAGE,
        'inputs': {key: {'path': str(path), 'sha256': sha}
                   for key, path, sha in args.inputs()},
        'containers_before': before,
        'next': 'graceful selected stop; native repair and pool-zero gates remain separate',
    }
    receipt(args.plan, value)


def reviewed_plan(args: argparse.Namespace) -> dict:
    value = json.loads(checked(args.plan, args.plan_sha256, private=True))
    need(value.get('schema') == 'bloom.selected-cutover-plan/1'
         and value.get('service') == 'bloom'
         and value.get('old_container_id') == args.old_container_id
         and value.get('image') == IMAGE
         and value.get('inputs') == {key: {'path': str(path), 'sha256': sha}
                                     for key, path, sha in args.inputs()},
         'reviewed cutover plan differs')
    return value


def stop(args: argparse.Namespace) -> None:
    planned = reviewed_plan(args)
    before = baseline(args)
    need(planned['containers_before'] == before,
         'fleet changed since reviewed plan')
    receipt(args.intent, {'schema': 'bloom.selected-stop-intent/1',
                          'plan_sha256': args.plan_sha256,
                          'container_id': args.old_container_id,
                          'state': 'stop_started'})
    try:
        output(['docker', 'stop', '--signal', 'SIGTERM', '--timeout', '-1', CONTAINER])
        after = inventory()
        need(same_siblings(before, after), 'sibling container changed during stop')
        old = after[CONTAINER]
        need(old['id'] == args.old_container_id and old['status'] == 'exited'
             and old['exit_code'] in (0, 143) and old['oom_killed'] is False,
             'Bloom did not exit cleanly')
        receipt(args.stop_receipt, {'schema': 'bloom.selected-stop/1',
                'plan_sha256': args.plan_sha256, 'container_id': args.old_container_id,
                'before': before, 'after': after, 'state': 'stopped_cleanly',
                'observed_at': datetime.now(timezone.utc).isoformat(),
                'db_pool_zero': 'separate_operator_proof_required'})
    except Exception as exc:
        receipt(args.failure_receipt, {'schema': 'bloom.selected-failure/1',
                'stage': 'stop', 'error_type': type(exc).__name__,
                'production_may_have_changed': True, 'automatic_rollback': False})
        raise


def deploy(args: argparse.Namespace) -> None:
    planned = reviewed_plan(args)
    stopped = json.loads(checked(args.stop_receipt, args.stop_sha256,
                                 private=True))
    need(stopped.get('schema') == 'bloom.selected-stop/1'
         and stopped.get('plan_sha256') == args.plan_sha256
         and stopped.get('container_id') == args.old_container_id
         and stopped.get('state') == 'stopped_cleanly'
         and stopped.get('before') == planned['containers_before'],
         'selected stop receipt differs')
    pool = json.loads(checked(args.pool_zero_receipt, args.pool_zero_sha256,
                              private=True))
    need(pool.get('schema') == 'bloom.writer-zero/v1'
         and pool.get('service') == 'bloom'
         and pool.get('container_id') == args.old_container_id
         and pool.get('database') == DATABASE
         and pool.get('schema_name') == SCHEMA
         and pool.get('read_only') is True
         and all(pool.get(key) == 0 for key in
                 ('active_bloom_sessions', 'prepared_transactions',
                  'remaining_bloom_processes')),
         'reviewed Bloom writer/pool-zero proof differs')
    stop_time = datetime.fromisoformat(stopped['observed_at'])
    pool_time = datetime.fromisoformat(pool['observed_at'])
    need(stop_time.tzinfo is not None and pool_time.tzinfo is not None
         and stop_time <= pool_time <= datetime.now(timezone.utc),
         'Bloom writer/pool-zero proof predates selected stop')
    repaired = json.loads(checked(args.repair_receipt, args.repair_sha256,
                                  private=True))
    need(repaired.get('schema') == 'dayhoff.producer-bounded-repair/1'
         and repaired.get('service') == 'bloom'
         and repaired.get('state') == 'verified'
         and repaired.get('mode') in ('apply', 'readback')
         and repaired.get('source_tag') == TAG
         and repaired.get('source_commit') == COMMIT
         and repaired.get('tapdb_version') == '10.1.4'
         and repaired.get('database') == DATABASE
         and repaired.get('schema_name') == SCHEMA
         and repaired.get('input_sha256') == EVIDENCE_SHA
         and repaired.get('selected') == 174
         and repaired.get('owner_count') == 79
         and repaired.get('readback', {}).get('verified') == 174,
         'Bloom 174-row repair is not terminal verified')
    need(digest(read(CONFIG)) == args.config_sha256
         and digest(read(COMPOSE)) == args.compose_sha256
         and digest(read(MANIFEST)) == args.manifest_sha256,
         'selected files changed after plan')
    candidate_changes(args)
    before = inventory()
    need(same_siblings(planned['containers_before'], before)
         and before[CONTAINER]['id'] == args.old_container_id
         and before[CONTAINER]['status'] == 'exited'
         and before[CONTAINER]['exit_code'] in (0, 143),
         'stopped Bloom/sibling baseline changed')
    stopped_selected = stopped.get('after', {}).get(CONTAINER)
    snapshot_keys = ('id', 'image_id', 'configured_image', 'service',
                     'status', 'exit_code', 'oom_killed', 'started_at', 'restarts')
    need(isinstance(stopped_selected, dict)
         and all(before[CONTAINER][key] == stopped_selected.get(key)
                 for key in snapshot_keys),
         'stopped Bloom lifecycle changed after stop receipt')
    target = image(IMAGE)
    manifest_after = candidate_changes(args)
    receipt(args.deploy_intent, {'schema': 'bloom.selected-deploy-intent/1',
            'plan_sha256': args.plan_sha256, 'stop_sha256': args.stop_sha256,
            'repair_sha256': args.repair_sha256,
            'pool_zero_sha256': args.pool_zero_sha256,
            'state': 'deployment_started'})
    stage = 'config'
    try:
        replace_exact(CONFIG, args.config_sha256,
                      read(args.config_candidate, private=True))
        stage = 'compose'
        replace_exact(COMPOSE, args.compose_sha256,
                      read(args.compose_candidate, private=True))
        stage = 'manifest'
        replace_exact(MANIFEST, args.manifest_sha256, manifest_after)
        stage = 'selected-start'
        output(['docker', 'compose', '-p', 'dayhoff-day', '-f', str(COMPOSE),
                '--progress', 'plain', 'up', '-d', '--no-deps',
                '--pull', 'never', '--no-build', 'bloom'])
        after = inventory()
        need(same_siblings(before, after), 'sibling container changed')
        now = after[CONTAINER]
        need(now['id'] != args.old_container_id
             and now['configured_image'] == IMAGE
             and now['image_id'] == target['Id']
             and now['status'] == 'running' and now['health'] != 'unhealthy',
             'selected Bloom replacement not running')
        need(digest(read(CONFIG)) == args.config_candidate_sha256
             and digest(read(COMPOSE)) == args.compose_candidate_sha256
             and digest(read(MANIFEST)) == digest(manifest_after),
             'installed selected files changed')
        receipt(args.deployment_receipt, {'schema': 'bloom.selected-cutover/1',
                'service': 'bloom', 'state': 'deployed',
                'image': IMAGE, 'source_tag': TAG, 'source_commit': COMMIT,
                'plan_sha256': args.plan_sha256,
                'stop_sha256': args.stop_sha256,
                'repair_sha256': args.repair_sha256,
                'pool_zero_sha256': args.pool_zero_sha256,
                'manifest_after_sha256': digest(manifest_after),
                'containers_before': before, 'containers_after': after,
                'observed_at': datetime.now(timezone.utc).isoformat(),
                'publication_refresh': 'pending', 'acceptance': 'pending'})
    except Exception as exc:
        receipt(args.failure_receipt, {'schema': 'bloom.selected-failure/1',
                'stage': stage, 'error_type': type(exc).__name__,
                'production_may_have_changed': True, 'automatic_rollback': False})
        raise


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=('plan', 'stop', 'deploy'))
    p.add_argument('--old-container-id', required=True)
    for name in ('config', 'compose', 'manifest', 'config-candidate',
                 'compose-candidate', 'bloom-token', 'atlas-token', 'build-receipt'):
        if name in ('config-candidate', 'compose-candidate', 'build-receipt'):
            p.add_argument('--' + name, required=True, type=Path)
        p.add_argument('--' + name + '-sha256', required=True)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--plan-sha256')
    p.add_argument('--intent', type=Path)
    p.add_argument('--stop-receipt', type=Path)
    p.add_argument('--stop-sha256')
    p.add_argument('--pool-zero-receipt', type=Path)
    p.add_argument('--pool-zero-sha256')
    p.add_argument('--repair-receipt', type=Path)
    p.add_argument('--repair-sha256')
    p.add_argument('--deploy-intent', type=Path)
    p.add_argument('--deployment-receipt', type=Path)
    p.add_argument('--failure-receipt', type=Path)
    args = p.parse_args()
    args.inputs = lambda: (
        ('config', CONFIG, args.config_sha256),
        ('compose', COMPOSE, args.compose_sha256),
        ('manifest', MANIFEST, args.manifest_sha256),
        ('config_candidate', args.config_candidate, args.config_candidate_sha256),
        ('compose_candidate', args.compose_candidate, args.compose_candidate_sha256),
        ('bloom_token', STAGE / 'bloom.token', args.bloom_token_sha256),
        ('atlas_token', STAGE / 'atlas.token', args.atlas_token_sha256),
        ('build_receipt', args.build_receipt, args.build_receipt_sha256),
    )
    os.umask(0o077)
    operator_host()
    if args.phase == 'plan':
        plan(args)
    elif args.phase == 'stop':
        need(all((args.plan_sha256, args.intent, args.stop_receipt,
                  args.failure_receipt)), 'stop plan/receipt paths required')
        stop(args)
    else:
        need(all((args.plan_sha256, args.stop_receipt, args.stop_sha256,
                  args.pool_zero_receipt, args.pool_zero_sha256,
                  args.repair_receipt, args.repair_sha256, args.deploy_intent,
                  args.deployment_receipt, args.failure_receipt)),
             'deploy terminal proof and receipt paths required')
        deploy(args)


if __name__ == '__main__':
    main()
