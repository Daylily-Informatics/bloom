# Becoming A Discoverable Service

In the Dayhoff bundle, a "discoverable service" is not a service that registers itself with a separate service-discovery daemon. It is a repo that follows the control-plane contract Dayhoff expects: a known activation path, a stable CLI, deployment-scoped runtime artifacts, deterministic bootstrap/start commands, and a readiness endpoint that proves the service is live.

Bloom already fits that model, but a few details matter if you are trying to understand how it becomes visible and runnable inside the broader stack.

## How Dayhoff Sees Bloom

`../../dayhoff/services/services.yaml` currently describes Bloom as:

| Field | Current catalog value |
| --- | --- |
| repo | `bloom` |
| role | `bloom` |
| cli | `bloom` |
| host port | `8912` |
| container port | `8912` |
| exposure | `private` |
| domain | `bloom` |
| liveness | `/healthz` |
| readiness | `/readyz` |

Bloom also appears in the `deploy_default` repo set alongside Atlas, Dewey, Ursa, Kahlo, and Zebra Day.

That is the bundle-level discoverability signal: Dayhoff knows Bloom exists, which port it wants, how to start it, and which readiness path to probe.

## Repo-Local Contract Bloom Must Expose

For Bloom to remain discoverable, the repo needs to keep exposing a stable local contract.

### 1. Activation Path

Bloom's repo entrypoint is:

```bash
source ./activate <deploy-name>
```

This is the first piece of the discoverability contract. Dayhoff expects each service repo to activate itself from its own root.

### 2. Deployment-Scoped Runtime Artifacts

Bloom's local state is deploy-name scoped:

```text
~/.config/bloom-<deploy-name>/bloom-config-<deploy-name>.yaml
~/.config/tapdb/bloom/bloom-<deploy-name>/tapdb-config.yaml
~/.config/tapdb/bloom/bloom-<deploy-name>/<tapdb-env>/uploads
```

This matters because Dayhoff's deploy model is built around `--deploy-name`. Service identity is not just a port number; it is the combination of repo, deploy name, config files, and runtime namespace.

### 3. Bootstrap

Bloom's current repo-local bootstrap command is:

```bash
bloom db build --target local
```

This is Bloom delegating runtime/bootstrap work to TapDB through its own supported CLI surface.

### 4. Start

Bloom's service start contract is:

```bash
bloom server start --port 8912
```

### 5. Readiness

Bloom's orchestrator-facing readiness path is:

```text
/readyz
```

The corresponding local probe is:

```bash
curl -k https://127.0.0.1:8912/readyz
```

## Important Catalog Drift To Know About

There is currently some drift between the Dayhoff service catalog and the repo-local Bloom contract:

- the service catalog still shows `conda_env_name: BLOOM`
- the catalog bootstrap command still shows `bloom db init` instead of `bloom db build --target local`
- repo-local Bloom now expects deployment-scoped env names like `BLOOM-<deploy-name>`
- repo-local Bloom's supported bootstrap command is `bloom db build --target local`

For actual Bloom operation, treat the repo-local Bloom CLI and docs as the current truth. The catalog entry should be kept aligned, but the service's own CLI is authoritative for how Bloom boots today.

## Host, Domain, Port, And Exposure

Current Dayhoff-facing Bloom identity is intentionally simple:

- local HTTPS port: `8912`
- private service domain label: `bloom`
- liveness: `/healthz`
- readiness: `/readyz`

For local direct use, that typically means:

```text
https://localhost:8912
https://127.0.0.1:8912/readyz
```

For Dayhoff-managed deployments, the final hostname and exposure pattern can be shaped by the broader deployment stack, ingress, and public-root-domain configuration. Bloom itself does not own that routing layer; it owns the predictable service behavior behind it.

## What Bloom Must Keep Stable To Stay Discoverable

Bloom stays easy for Dayhoff and sibling services to find when these remain stable:

- repo-root `activate`
- `bloom` CLI entrypoint
- deployment-scoped YAML and TapDB config conventions
- the service port and readiness endpoint
- the HTTP API location and GUI root

If one of those changes, Bloom is still the same service in a code sense, but it becomes harder for the rest of the ecology to find and run consistently.

## Bloom's Role In "Finding What Is Running, Where"

Bloom helps answer that question in two different ways.

### Material-State Discovery

At the domain level, Bloom helps other systems find:

- which material exists
- which container it is in
- which lineage edges produced it
- which external references connect it back to Atlas and the rest of the stack

### Service-Level Discovery

At the operational level, Bloom participates in Dayhoff's discoverability model by being a well-behaved service repo:

- predictable activation
- predictable config paths
- predictable bootstrap and start commands
- predictable health probes

So Bloom is not a general service registry, but it is a discoverable node in a convention-driven stack.

## Practical Checklist

If you are making Bloom newly deployable in a Dayhoff environment, the practical checklist is:

1. Ensure the repo activates with `source ./activate <deploy-name>`.
2. Ensure Bloom config is present at the deployment-scoped YAML path.
3. Ensure the TapDB namespace config exists and matches the deploy name.
4. Bootstrap with `bloom db build --target local`.
5. Start with `bloom server start --port 8912`.
6. Verify `https://127.0.0.1:8912/readyz`.
7. Make sure Dayhoff's service catalog and repo-local CLI contract agree.

If those seven steps work, Bloom is discoverable in the Dayhoff sense.
