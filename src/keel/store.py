"""SQLite schema and queries for Keel traces and benchmark results."""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any

from keel.models import CompactionRecord, Episode, Pin, RequestRecord, RunInfo

DDL: str = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, config_json TEXT NOT NULL,
  extracted_upto INTEGER NOT NULL DEFAULT 0, extracted_hash TEXT);
CREATE TABLE IF NOT EXISTS requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT REFERENCES sessions(id),
  turn_idx INTEGER NOT NULL, upstream_model TEXT NOT NULL, status INTEGER NOT NULL,
  cache_status TEXT NOT NULL, compacted INTEGER NOT NULL DEFAULT 0, tokenizer TEXT NOT NULL,
  tokens_in_raw INTEGER NOT NULL, tokens_in_sent INTEGER NOT NULL, tokens_out INTEGER,
  pin_tokens INTEGER NOT NULL DEFAULT 0, proxy_ms REAL NOT NULL, upstream_ms REAL NOT NULL,
  llm_ms REAL NOT NULL DEFAULT 0, error TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_requests_session ON requests(session_id, turn_idx);
CREATE TABLE IF NOT EXISTS compactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id),
  turn_idx INTEGER NOT NULL, strategy TEXT NOT NULL, prefix_len INTEGER NOT NULL,
  prefix_hash TEXT NOT NULL, prefix_hashes_json TEXT NOT NULL,
  tokens_before INTEGER NOT NULL, tokens_after INTEGER NOT NULL,
  evicted_json TEXT NOT NULL, compacted_json TEXT NOT NULL, summary_text TEXT,
  pins_injected_json TEXT NOT NULL DEFAULT '[]', validator_json TEXT,
  llm_tokens INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_compactions_session ON compactions(session_id, active);
CREATE TABLE IF NOT EXISTS pins (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id),
  text TEXT NOT NULL, source TEXT NOT NULL CHECK (source IN ('explicit','auto')),
  source_turn INTEGER, confidence REAL NOT NULL DEFAULT 1.0,
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, started_at TEXT NOT NULL, git_sha TEXT NOT NULL, config_json TEXT NOT NULL,
  model_hashes_json TEXT NOT NULL, seeds_json TEXT NOT NULL, args_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS episodes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id),
  scenario_id TEXT NOT NULL, kind TEXT NOT NULL, model TEXT NOT NULL, condition TEXT NOT NULL,
  seed INTEGER NOT NULL, violated INTEGER NOT NULL, constraint_survived INTEGER,
  summary_survived INTEGER, task_done INTEGER NOT NULL, validator_missing INTEGER,
  auto_pins_total INTEGER, auto_pins_tp INTEGER, session_id TEXT NOT NULL,
  probe_json TEXT NOT NULL DEFAULT '[]', error TEXT, created_at TEXT NOT NULL,
  UNIQUE (run_id, scenario_id, model, condition, seed));
"""


def utcnow() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


class Store:
    """One sqlite3 connection, check_same_thread=False, guarded by a threading.Lock."""

    def __init__(self, path: str) -> None:
        """Open (or create) the database at `path` (":memory:" allowed) and run the DDL."""
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._conn.executescript(DDL)
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.commit()

    def close(self) -> None:
        """Close the connection."""
        self._conn.close()

    def ensure_session(self, session_id: str, config: dict[str, Any]) -> None:
        """Create the session row if missing; an existing session keeps its config."""
        raise NotImplementedError("T-08")

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Return {id, created_at, config, extracted_upto, extracted_hash} or None."""
        raise NotImplementedError("T-08")

    def set_extracted(self, session_id: str, upto: int, last_hash: str | None) -> None:
        """Advance the auto-extraction cursor of a session."""
        raise NotImplementedError("T-08")

    def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        """Sessions newest first with n_requests and n_compactions."""
        raise NotImplementedError("T-08")

    def next_turn_idx(self, session_id: str) -> int:
        """Number of requests already logged for the session."""
        raise NotImplementedError("T-08")

    def insert_request(self, rec: RequestRecord) -> int:
        """Insert a request row and return its id."""
        raise NotImplementedError("T-08")

    def list_requests(self, session_id: str) -> list[dict[str, Any]]:
        """All request rows of a session, ordered by id."""
        raise NotImplementedError("T-08")

    def insert_compaction(self, rec: CompactionRecord) -> int:
        """Insert a compaction record and return its id."""
        raise NotImplementedError("T-08")

    def active_compactions(self, session_id: str) -> list[CompactionRecord]:
        """Active compaction records, prefix_len ascending."""
        raise NotImplementedError("T-08")

    def list_compactions(self, session_id: str) -> list[CompactionRecord]:
        """All compaction records, id ascending."""
        raise NotImplementedError("T-08")

    def deactivate_compactions(self, ids: list[int]) -> None:
        """Mark the given compaction records inactive."""
        raise NotImplementedError("T-08")

    def add_pin(self, pin: Pin) -> Pin:
        """Insert a pin; an active pin with the same session and text is returned instead."""
        raise NotImplementedError("T-08")

    def list_pins(self, session_id: str, active_only: bool = False) -> list[Pin]:
        """Pins of a session, ordered by id."""
        raise NotImplementedError("T-08")

    def deactivate_pin(self, session_id: str, pin_id: int) -> bool:
        """Deactivate a pin; True only if a row in that session changed."""
        raise NotImplementedError("T-08")

    def insert_run(self, run: RunInfo) -> None:
        """Insert a run row (INSERT OR IGNORE)."""
        raise NotImplementedError("T-08")

    def get_run(self, run_id: str) -> RunInfo | None:
        """Return the run or None."""
        raise NotImplementedError("T-08")

    def episode_exists(
        self, run_id: str, scenario_id: str, model: str, condition: str, seed: int
    ) -> bool:
        """True if the episode's unique key already exists."""
        raise NotImplementedError("T-08")

    def insert_episode(self, ep: Episode) -> int:
        """Insert an episode and return its id."""
        raise NotImplementedError("T-08")

    def list_episodes(self, run_id: str) -> list[Episode]:
        """All episodes of a run, ordered by id."""
        raise NotImplementedError("T-08")

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Run a read-only query and return rows as dicts."""
        raise NotImplementedError("T-08")
