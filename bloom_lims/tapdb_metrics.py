"""TapDB DB query metrics (TSV, 2-week rotation).

This module is adapted from the TapDB GUI implementation so Bloom can:
1) collect per-query latency metrics via SQLAlchemy Engine events
2) render the same metrics context as TapDB's `/admin/metrics`

Metrics settings come from the explicit TapDB config selected by Bloom's
service config. Metrics are best-effort and may be dropped under load to
avoid impacting request latency.
"""

from __future__ import annotations

import os
import queue
import re
import sys
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from daylily_tapdb.cli.db_config import get_admin_settings_for_env
from sqlalchemy import event
from sqlalchemy.engine import Engine

from bloom_lims.config import apply_runtime_environment, get_settings

request_path_var: ContextVar[str] = ContextVar("tapdb_request_path", default="")
request_method_var: ContextVar[str] = ContextVar("tapdb_request_method", default="")
db_username_var: ContextVar[str] = ContextVar("tapdb_db_username", default="")

_HEADER = (
    "ts_utc\t"
    "duration_ms\t"
    "ok\t"
    "op\t"
    "table_hint\t"
    "path\t"
    "method\t"
    "username\t"
    "rowcount\t"
    "error_type\n"
)


def _parse_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _resolved_bloom_runtime(
    env_name: str | None = None,
) -> tuple[str, Path, dict[str, object]]:
    ctx = apply_runtime_environment(get_settings())
    resolved_env = str(env_name or ctx.env).strip().lower() or ctx.env
    config_path = Path(ctx.config_path).expanduser().resolve()
    admin_settings = get_admin_settings_for_env(
        resolved_env,
        config_path=config_path,
        client_id=ctx.client_id,
        database_name=ctx.database_name,
    )
    return resolved_env, config_path, admin_settings


def metrics_enabled(env_name: str | None = None) -> bool:
    enabled = _resolved_bloom_runtime(env_name)[2].get("metrics_enabled")
    if isinstance(enabled, bool):
        return enabled
    if "pytest" in sys.modules:
        return False
    return True


def _sanitize_tsv(value: object) -> str:
    s = str(value or "")
    return s.replace("\t", " ").replace("\r", " ").replace("\n", " ")


_OP_RE = re.compile(r"^\s*([A-Za-z]+)")
_FROM_RE = re.compile(r"\bFROM\s+([A-Za-z0-9_\".]+)", re.IGNORECASE)
_INTO_RE = re.compile(r"\bINTO\s+([A-Za-z0-9_\".]+)", re.IGNORECASE)
_UPDATE_RE = re.compile(r"^\s*UPDATE\s+([A-Za-z0-9_\".]+)", re.IGNORECASE)
_DELETE_RE = re.compile(r"^\s*DELETE\s+FROM\s+([A-Za-z0-9_\".]+)", re.IGNORECASE)


def _extract_op(statement: str) -> str:
    m = _OP_RE.match(statement or "")
    if not m:
        return "OTHER"
    op = m.group(1).upper()
    if op in {"SELECT", "INSERT", "UPDATE", "DELETE"}:
        return op
    return "OTHER"


def _extract_table_hint(statement: str, op: str) -> str:
    stmt = (statement or "")[:1200]
    if op == "SELECT":
        m = _FROM_RE.search(stmt)
    elif op == "INSERT":
        m = _INTO_RE.search(stmt)
    elif op == "UPDATE":
        m = _UPDATE_RE.search(stmt)
    elif op == "DELETE":
        m = _DELETE_RE.search(stmt)
    else:
        m = None
    if not m:
        return ""
    hint = m.group(1).strip().strip('"')
    return hint


def _metrics_root_dir(env_name: str) -> Path:
    resolved_env, config_path, _admin_settings = _resolved_bloom_runtime(env_name)
    return config_path.parent / resolved_env / "metrics"


def two_week_period_start_utc(now_utc: datetime) -> datetime:
    """Return Monday 00:00Z for the ISO-week pair containing now_utc."""
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    iso_year, iso_week, _iso_weekday = now_utc.isocalendar()
    start_week = iso_week - ((iso_week - 1) % 2)
    start_date = datetime.fromisocalendar(iso_year, start_week, 1).date()
    return datetime(
        start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc
    )


def current_metrics_path(
    env_name: str,
    *,
    now_utc: Optional[datetime] = None,
    create_dirs: bool = True,
) -> Path:
    now = now_utc or datetime.now(timezone.utc)
    period_start = two_week_period_start_utc(now)
    root = _metrics_root_dir(env_name)
    if create_dirs:
        root.mkdir(parents=True, exist_ok=True)
    return root / f"db_metrics_{period_start:%Y%m%d}.tsv"


@dataclass(frozen=True)
class MetricsRow:
    ts_utc: str
    duration_ms: str
    ok: str
    op: str
    table_hint: str
    path: str
    method: str
    username: str
    rowcount: str
    error_type: str

    def to_tsv_line(self) -> str:
        return (
            f"{self.ts_utc}\t"
            f"{self.duration_ms}\t"
            f"{self.ok}\t"
            f"{self.op}\t"
            f"{self.table_hint}\t"
            f"{self.path}\t"
            f"{self.method}\t"
            f"{self.username}\t"
            f"{self.rowcount}\t"
            f"{self.error_type}\n"
        )


class TSVMetricsWriter:
    def __init__(self, env_name: str):
        self._env_name = (env_name or "dev").strip().lower()
        admin_settings = _resolved_bloom_runtime(self._env_name)[2]
        self._queue_max = int(admin_settings.get("metrics_queue_max", 20000))
        self._flush_secs = float(admin_settings.get("metrics_flush_seconds", 1.0))
        self._queue: queue.Queue[str] = queue.Queue(maxsize=self._queue_max)
        self._dropped = 0
        self._dropped_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="tapdb-db-metrics", daemon=True
        )
        self._thread.start()

    def enqueue(self, row: MetricsRow) -> None:
        try:
            self._queue.put_nowait(row.to_tsv_line())
        except queue.Full:
            with self._dropped_lock:
                self._dropped += 1

    def dropped_count(self) -> int:
        with self._dropped_lock:
            return int(self._dropped)

    def stop(self, *, timeout: float = 2.0) -> None:
        self._stop.set()
        self._thread.join(timeout=timeout)
        # Best-effort flush after stop.
        self._flush_batch(max_lines=50000)

    def _flush_batch(self, *, max_lines: int) -> None:
        lines: list[str] = []
        for _ in range(max_lines):
            try:
                lines.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if not lines:
            return

        path = current_metrics_path(self._env_name)
        is_new = not path.exists() or path.stat().st_size == 0
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            if is_new:
                f.write(_HEADER)
            f.writelines(lines)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._flush_batch(max_lines=5000)
            self._stop.wait(self._flush_secs)


_writer_lock = threading.Lock()
_writers_by_env: dict[str, TSVMetricsWriter] = {}


def _get_writer(env_name: str) -> Optional[TSVMetricsWriter]:
    if not metrics_enabled():
        return None
    env = (env_name or "dev").strip().lower()
    with _writer_lock:
        writer = _writers_by_env.get(env)
        if writer is None:
            writer = TSVMetricsWriter(env)
            _writers_by_env[env] = writer
        return writer


def get_dropped_count(env_name: str) -> int:
    env = (env_name or "dev").strip().lower()
    with _writer_lock:
        writer = _writers_by_env.get(env)
    return writer.dropped_count() if writer else 0


def stop_all_writers() -> None:
    with _writer_lock:
        writers = list(_writers_by_env.values())
        _writers_by_env.clear()
    for writer in writers:
        try:
            writer.stop()
        except Exception:
            # Best-effort; do not raise during shutdown.
            pass


_installed_engine_ids: set[int] = set()
_installed_lock = threading.Lock()


def maybe_install_engine_metrics(engine: Engine, *, env_name: str) -> None:
    if not metrics_enabled():
        return
    engine_id = id(engine)
    with _installed_lock:
        if engine_id in _installed_engine_ids:
            return
        _installed_engine_ids.add(engine_id)

    writer = _get_writer(env_name)
    if writer is None:
        return

    def _before_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        _ = parameters, context, executemany
        start = time.perf_counter()
        op = _extract_op(statement)
        table_hint = _extract_table_hint(statement, op)
        conn.info.setdefault("_tapdb_metrics", {})[id(cursor)] = (start, op, table_hint)

    def _after_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        _ = statement, parameters, context, executemany
        start, op, table_hint = conn.info.get("_tapdb_metrics", {}).pop(
            id(cursor), (None, "OTHER", "")
        )
        if start is None:
            return
        duration_ms = (time.perf_counter() - start) * 1000.0
        rowcount = getattr(cursor, "rowcount", None)
        writer.enqueue(
            MetricsRow(
                ts_utc=datetime.now(timezone.utc).isoformat(),
                duration_ms=f"{duration_ms:.3f}",
                ok="1",
                op=_sanitize_tsv(op),
                table_hint=_sanitize_tsv(table_hint),
                path=_sanitize_tsv(request_path_var.get()),
                method=_sanitize_tsv(request_method_var.get()),
                username=_sanitize_tsv(db_username_var.get()),
                rowcount="" if rowcount is None else str(int(rowcount)),
                error_type="",
            )
        )

    def _handle_error(exception_context):
        conn = exception_context.connection
        cursor = getattr(exception_context, "cursor", None)
        if conn is None or cursor is None:
            return None
        start, op, table_hint = conn.info.get("_tapdb_metrics", {}).pop(
            id(cursor), (None, "OTHER", "")
        )
        duration_ms = (
            (time.perf_counter() - start) * 1000.0 if start is not None else 0.0
        )
        err = getattr(exception_context, "original_exception", None)
        error_type = err.__class__.__name__ if err is not None else "Error"
        writer.enqueue(
            MetricsRow(
                ts_utc=datetime.now(timezone.utc).isoformat(),
                duration_ms=f"{duration_ms:.3f}",
                ok="0",
                op=_sanitize_tsv(op),
                table_hint=_sanitize_tsv(table_hint),
                path=_sanitize_tsv(request_path_var.get()),
                method=_sanitize_tsv(request_method_var.get()),
                username=_sanitize_tsv(db_username_var.get()),
                rowcount="",
                error_type=_sanitize_tsv(error_type),
            )
        )
        return None

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(engine, "after_cursor_execute", _after_cursor_execute)
    event.listen(engine, "handle_error", _handle_error)


def _tail_lines(path: Path, *, max_lines: int) -> list[str]:
    """Return up to max_lines of the last lines in a file (utf-8).

    This avoids reading the entire file when it grows large.
    """

    if max_lines <= 0:
        return []
    if not path.exists():
        return []
    block_size = 8192
    data = b""
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        remaining = f.tell()
        while remaining > 0 and data.count(b"\n") <= max_lines:
            step = block_size if remaining >= block_size else remaining
            remaining -= step
            f.seek(remaining)
            data = f.read(step) + data
    lines = data.splitlines()[-max_lines:]
    try:
        return [ln.decode("utf-8", errors="replace") for ln in lines]
    except Exception:
        return []


def read_recent_metrics(env_name: str, *, max_lines: int) -> list[dict]:
    path = current_metrics_path(env_name, create_dirs=False)
    lines = _tail_lines(path, max_lines=max_lines + 1)  # include possible header
    rows: list[dict] = []
    for raw in lines:
        if not raw or raw.startswith("ts_utc\t"):
            continue
        parts = raw.split("\t")
        if len(parts) < 10:
            continue
        rows.append(
            {
                "ts_utc": parts[0],
                "duration_ms": float(parts[1]) if parts[1] else 0.0,
                "ok": parts[2] == "1",
                "op": parts[3],
                "table_hint": parts[4],
                "path": parts[5],
                "method": parts[6],
                "username": parts[7],
                "rowcount": parts[8],
                "error_type": parts[9].strip(),
            }
        )
    return rows


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    if p <= 0:
        return float(sorted_values[0])
    if p >= 100:
        return float(sorted_values[-1])
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return float(sorted_values[f])
    d0 = sorted_values[f] * (c - k)
    d1 = sorted_values[c] * (k - f)
    return float(d0 + d1)


def summarize_metrics(rows: Iterable[dict]) -> dict:
    rows_list = list(rows)
    durations = sorted([float(r.get("duration_ms") or 0.0) for r in rows_list])
    last_seen = ""
    if rows_list:
        last_seen = str(rows_list[-1].get("ts_utc") or "")

    def _group_by(key: str) -> list[dict]:
        buckets: dict[str, list[float]] = {}
        for r in rows_list:
            k = str(r.get(key) or "")
            buckets.setdefault(k, []).append(float(r.get("duration_ms") or 0.0))
        out = []
        for k, vals in buckets.items():
            s = sorted(vals)
            out.append(
                {
                    key: k,
                    "count": len(vals),
                    "p95_ms": _percentile(s, 95.0),
                    "max_ms": max(vals) if vals else 0.0,
                }
            )
        out.sort(
            key=lambda d: (d.get("p95_ms") or 0.0, d.get("count") or 0), reverse=True
        )
        return out

    slowest = sorted(
        rows_list, key=lambda r: float(r.get("duration_ms") or 0.0), reverse=True
    )[:25]
    return {
        "count": len(rows_list),
        "p50_ms": _percentile(durations, 50.0),
        "p95_ms": _percentile(durations, 95.0),
        "p99_ms": _percentile(durations, 99.0),
        "max_ms": float(durations[-1]) if durations else 0.0,
        "last_seen": last_seen,
        "slowest": slowest,
        "by_path": _group_by("path"),
        "by_table": _group_by("table_hint"),
    }


def build_metrics_page_context(env_name: str, *, limit: int = 5000) -> dict:
    env = (env_name or "dev").strip().lower()
    clamped = max(1, min(int(limit), 20000))
    now = datetime.now(timezone.utc)
    period_start = two_week_period_start_utc(now)

    enabled = metrics_enabled()
    try:
        path = current_metrics_path(env, now_utc=now, create_dirs=enabled)
    except Exception as exc:
        enabled = False
        path = Path("/") / "tapdb_db_metrics_unavailable.tsv"
        summary = summarize_metrics([])
        return {
            "metrics_enabled": enabled,
            "metrics_message": f"Failed to resolve metrics path: {exc}",
            "metrics_file": str(path),
            "period_start_utc": period_start.isoformat(),
            "limit": clamped,
            "dropped_count": 0,
            "summary": summary,
        }

    message = ""
    rows: list[dict] = []
    if enabled:
        try:
            rows = read_recent_metrics(env, max_lines=clamped)
        except Exception as exc:
            message = f"Failed to read metrics: {exc}"
            rows = []
    summary = summarize_metrics(rows)
    dropped = get_dropped_count(env)

    if not enabled:
        message = "DB metrics collection is disabled. Set TAPDB_DB_METRICS=1 to enable."
    elif not path.exists() and not message:
        message = "No metrics file yet for the current period. Generate some DB traffic and refresh."

    return {
        "metrics_enabled": enabled,
        "metrics_message": message,
        "metrics_file": str(path),
        "period_start_utc": period_start.isoformat(),
        "limit": clamped,
        "dropped_count": dropped,
        "summary": summary,
    }
