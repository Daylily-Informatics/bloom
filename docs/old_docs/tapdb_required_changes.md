# TapDB Required Changes

Bloom beta queue operations now bypass the retired `/api/v1/actions/execute` surface and write explicit queue, lineage, run, and resolver state directly.

One shared-library gap remains for full convergence on modern TapDB actions:

- Bloom does not yet have first-class modern TapDB action templates for beta lab-operation records such as queue transition, extraction completion, QC disposition, library prep completion, pool creation, and sequencing run completion.

Current Bloom-side behavior:

- beta operations are deterministic and idempotent
- beta operations create explicit Bloom records and lineage
- beta APIs do not depend on legacy `action_template` fallback or Bloom `do_action` execution

Required TapDB follow-up for full action-model convergence:

1. Define modern action templates for beta wet-lab operations.
2. Expose a clean programmatic path for recording those action instances without the legacy Bloom `do_action_*` runtime.
3. Keep the contract EUID-only and namespace-safe across Bloom, Atlas, and Ursa.

This gap does not block the Bloom beta queue API or the run resolver, but it does block complete removal of all legacy action-recording internals from the wider Bloom codebase.
