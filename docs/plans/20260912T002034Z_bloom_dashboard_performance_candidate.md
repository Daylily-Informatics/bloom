# Bloom dashboard performance candidate, round 1

Status: prepared for operator measurement; not deployed.

Baseline: Bloom commit `0407d2984f3b316e5543c0f90799676b8f1f97e0` with TapDB `10.1.3`. The controlling migration ledger owns integration, live measurements and deployment. The user permits at most two improvement rounds, targets half the response time, and allows completion below that target if performance does not regress.

The dashboard page and statistics API currently fetch every active generic instance and its complete metadata before computing counts and recent items. This candidate groups counts in PostgreSQL, returns only the displayed columns of at most five recent rows per list, and closes each request's database session and engine. It introduces no cache, schema change, template mutation, identity allocation, authorization change or new dependency.

The GUI retains its existing open-work-item count; the API retains its queue-definition and workflow counts. Python continues to normalize the small grouped kind/status values exactly as before. The GUI recent-object query preserves its existing creation-time ordering without adding a tie-breaker. Filtered queue/workflow lists use creation time descending and UID ascending; compare actual membership before accepting the candidate. The API now reports a database failure instead of silently returning partial zero counts.

Local evidence: three focused in-memory SQL tests passed, covering counts and normalization, deleted rows, bounded recent results, exclusion of full metadata from result columns, and access after session closure. Ruff and `git diff --check` passed. These are correctness checks, not a production speed claim. The existing operator virtual environment was reused with the exact released TapDB pin; no production data was copied.

Operator acceptance: compare baseline and candidate on the same upgraded host, data, runtime principal and authenticated requests. Retain compact timing samples and response-parity evidence for the dashboard page and statistics API, plus an unchanged graph read and the existing read/write/replay acceptance. Account for deterministic ordering where creation timestamps tie. Keep the candidate only if measured performance does not regress; use at most one further improvement round. Any required replacement image must be recorded under the user's performance amendment. Preserve the native migration checkpoint and all allocator exposures.
