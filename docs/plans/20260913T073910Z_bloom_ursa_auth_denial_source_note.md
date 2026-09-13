# Bloom F11 Ursa sequencing authentication diagnosis

## Gate 0 and evidence

- Worktree: `/Users/jmajor/projects/mega_dayhoff/.codex-worktrees/ursa-final-gap-bloom-20260913`; branch `codex/ursa-final-gap-bloom-20260913`; clean baseline at deployed Bloom 10.0.4 commit `7ab0e96bccba316154b8dc775e59a4daa2c6930e`.
- Original checkout `/Users/jmajor/projects/mega_dayhoff/repos_work/bloom-tapdb10-performance-integrated` has dirty `AGENTS.md` and newer source/evidence; left unchanged.
- Controlling F11 plan: `/Users/jmajor/projects/mega_dayhoff/.codex-worktrees/ursa-gui-simplification-20260912/docs/plans/20260913T065833Z_ursa_final_gap_closure_ledger.md`. Saved prior handoff: `docs/plans/20260912T042640Z_ursa_gui_simplification_evidence/lead/20260912_bloom_search_dependency.md` in that Ursa worktree.
- Lead reported an authenticated Ursa 14.0.6 ONT sequencing search failure. Read-only Bloom log retrieval used existing SSM profile `lsmc`, region `us-west-2`, EC2 `i-07df3a933e4839f52`, container `dayhoff-day-bloom-1`; no shared interactive session was touched.
- SSM log receipts: `35900d0a-37d8-46bf-968a-7b52e9ce6515` (since 07:34, no output); `371f4947-b96f-4297-8767-8ec6d323233a` (tail 180, auth stack); `ab98e598-1dc6-4264-a7b4-b627c4a87201` (timestamped tail 180).
- Timestamped exception at `2026-09-13T07:33:39.761517347Z`: `PermissionError: Token owner '3364' has no explicit Bloom role`. Owner identifier is from the actual logged token record, not an invented mapping. No token value was printed or copied.
- Stack: `bloom_lims/api/v1/dependencies.py:get_api_user` -> `_authenticate_bloom_token` -> `bloom_lims/auth/services/user_api_tokens.py:constrained_roles_for_token_owner`.

## Confirmed defect and bounded repair

Bloom validates the existing token, then its owner-role guard raises `PermissionError` when the owner cannot be resolved or has no explicit stored role. The API dependency did not translate this denial, so it escaped as HTTP 500 before the search handler. The observed failure does not establish a defect in search results or Ursa's response parser.

Source repair complete in `bloom_lims/api/v1/dependencies.py`: translate the existing guard's `PermissionError` into HTTP 403 with `detail="Bloom API token owner authorization was rejected"`, preserving the role guard and chained server-side cause. The public denial does not expose the owner identifier. No identity, role, group, token, data, runtime config, or credential changes. Source reviewed with targeted `git diff`; no executable checks run.

## Owner-resolution source findings

- `bloom_lims/auth/repositories/tapdb/users.py` selects the exact numeric `generic_instance.uid` for owner `3364`, constrained to active, undeleted `actor_instance`, category `actor`, type `user`, subtype `system`. It reads `role`, `login_identifier`, and `email` from the top level of `json_addl`. The call includes inactive users but still excludes deleted rows. Numeric lookup failure proceeds to the existing login/email lookup of that literal identifier; no such behavior was added in this repair.
- `scripts/bloom_tapdb10_conversion.py:_converted_payload` preserves the original JSON via deep copy and adds an empty `properties` envelope when missing. Its declared historical graph cleanup affects graph metadata, not owner role or numeric UID. The inspected conversion source does not support a claim that roles moved under `properties` or that user `3364` was renumbered.
- Bloom's public user CLI exposes `provision-local` and `issue-token`, both mutations; neither was used. TapDB's existing `user list` output omits UID and normalizes stored roles to admin/user, so it cannot alone prove this exact Bloom owner or canonical role. An existing authenticated owner read or an explicitly supported owner helper is needed to distinguish missing/deleted/mismatched owner from an empty role without fabrication.

## Exact owner read and remaining blocker

The lead explicitly authorized the existing read-only helper used by public authentication because the user CLI does not expose the necessary read. On the unchanged deployed Bloom container, `BLOOMdb3` plus `resolve_user_record(session, "3364", include_inactive=True)` returned exactly `{"found": false, "requested_user_id": "3364"}`. SSM receipt `94dc1471-bf81-4e2f-90f7-4664a250f806` completed successfully. The helper closed the database handle and did not provision a user, mint a token, write roles, change config, patch runtime auth, or issue raw SQL. No credential contents were opened or printed.

The existing token therefore references an owner that Bloom's canonical user resolver cannot find; the observed runtime defect is not merely a role-string formatting error. This read does not establish whether a historical deleted or differently typed row exists, and it supplies no authorized replacement identity. Successful search remains blocked on authoritative identification and reconciliation of that existing token owner. Do not infer an owner from a nearby UID or assign a default role. This agent stops the identity branch at the precise missing-owner evidence.

The 403 source fix is ready for lead-owned release review. Ursa currently maps upstream 401/403 to its integration-unavailable response; this change removes the misleading upstream-500 classification without claiming Ursa emits 403 itself. No tests, lint, CI, builds, commits, tags, pushes, deployments or schema/data mutations were run by this agent.
