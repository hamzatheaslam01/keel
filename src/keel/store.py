"""SQLite schema and queries for Keel traces and benchmark results."""

from __future__ import annotations

import json
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


def _dumps(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False)


def _opt_int(x: bool | None) -> int | None:
    return None if x is None else int(x)


def _opt_bool(x: int | None) -> bool | None:
    return None if x is None else bool(x)


def _compaction(r: sqlite3.Row) -> CompactionRecord:
    return CompactionRecord(
        id=r["id"], session_id=r["session_id"], turn_idx=r["turn_idx"], strategy=r["strategy"],
        prefix_len=r["prefix_len"], prefix_hash=r["prefix_hash"],
        prefix_hashes=json.loads(r["prefix_hashes_json"]), tokens_before=r["tokens_before"],
        tokens_after=r["tokens_after"], evicted=json.loads(r["evicted_json"]),
        compacted=json.loads(r["compacted_json"]), summary_text=r["summary_text"],
        pins_injected=json.loads(r["pins_injected_json"]),
        validator=None if r["validator_json"] is None else json.loads(r["validator_json"]),
        llm_tokens=r["llm_tokens"], active=bool(r["active"]),
    )


def _pin(r: sqlite3.Row) -> Pin:
    return Pin(
        id=r["id"], session_id=r["session_id"], text=r["text"], source=r["source"],
        source_turn=r["source_turn"], confidence=r["confidence"], active=bool(r["active"]),
    )


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

    def _write(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _rows(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # sessions

    def ensure_session(self, session_id: str, config: dict[str, Any]) -> None:
        """Create the session row if missing; an existing session keeps its config."""
        self._write(
            "INSERT OR IGNORE INTO sessions (id, created_at, config_json) VALUES (?,?,?)",
            (session_id, utcnow(), _dumps(config)),
        )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Return {id, created_at, config, extracted_upto, extracted_hash} or None."""
        rows = self._rows("SELECT * FROM sessions WHERE id=?", (session_id,))
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r["id"],
            "created_at": r["created_at"],
            "config": json.loads(r["config_json"]),
            "extracted_upto": r["extracted_upto"],
            "extracted_hash": r["extracted_hash"],
        }

    def set_extracted(self, session_id: str, upto: int, last_hash: str | None) -> None:
        """Advance the auto-extraction cursor of a session."""
        self._write(
            "UPDATE sessions SET extracted_upto=?, extracted_hash=? WHERE id=?",
            (upto, last_hash, session_id),
        )

    def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        """Sessions newest first with n_requests and n_compactions."""
        rows = self._rows(
            "SELECT s.id, s.created_at,"
            " (SELECT COUNT(*) FROM requests r WHERE r.session_id=s.id) AS n_requests,"
            " (SELECT COUNT(*) FROM compactions c WHERE c.session_id=s.id) AS n_compactions"
            " FROM sessions s ORDER BY s.created_at DESC, s.rowid DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    # requests

    def next_turn_idx(self, session_id: str) -> int:
        """Number of requests already logged for the session."""
        rows = self._rows("SELECT COUNT(*) AS n FROM requests WHERE session_id=?", (session_id,))
        return int(rows[0]["n"])

    def insert_request(self, rec: RequestRecord) -> int:
        """Insert a request row and return its id."""
        cur = self._write(
            "INSERT INTO requests (session_id, turn_idx, upstream_model, status, cache_status,"
            " compacted, tokenizer, tokens_in_raw, tokens_in_sent, tokens_out, pin_tokens,"
            " proxy_ms, upstream_ms, llm_ms, error, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rec.session_id, rec.turn_idx, rec.upstream_model, rec.status, rec.cache_status,
                int(rec.compacted), rec.tokenizer, rec.tokens_in_raw, rec.tokens_in_sent,
                rec.tokens_out, rec.pin_tokens, rec.proxy_ms, rec.upstream_ms, rec.llm_ms,
                rec.error, utcnow(),
            ),
        )
        return int(cur.lastrowid)

    def list_requests(self, session_id: str) -> list[dict[str, Any]]:
        """All request rows of a session, ordered by id."""
        rows = self._rows("SELECT * FROM requests WHERE session_id=? ORDER BY id", (session_id,))
        return [dict(r) for r in rows]

    # compactions

    def insert_compaction(self, rec: CompactionRecord) -> int:
        """Insert a compaction record and return its id."""
        cur = self._write(
            "INSERT INTO compactions (session_id, turn_idx, strategy, prefix_len, prefix_hash,"
            " prefix_hashes_json, tokens_before, tokens_after, evicted_json, compacted_json,"
            " summary_text, pins_injected_json, validator_json, llm_tokens, active, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rec.session_id, rec.turn_idx, rec.strategy, rec.prefix_len, rec.prefix_hash,
                _dumps(rec.prefix_hashes), rec.tokens_before, rec.tokens_after,
                _dumps(rec.evicted), _dumps(rec.compacted), rec.summary_text,
                _dumps(rec.pins_injected),
                None if rec.validator is None else _dumps(rec.validator),
                rec.llm_tokens, int(rec.active), utcnow(),
            ),
        )
        return int(cur.lastrowid)

    def active_compactions(self, session_id: str) -> list[CompactionRecord]:
        """Active compaction records, prefix_len ascending."""
        rows = self._rows(
            "SELECT * FROM compactions WHERE session_id=? AND active=1"
            " ORDER BY prefix_len ASC, id ASC",
            (session_id,),
        )
        return [_compaction(r) for r in rows]

    def list_compactions(self, session_id: str) -> list[CompactionRecord]:
        """All compaction records, id ascending."""
        rows = self._rows(
            "SELECT * FROM compactions WHERE session_id=? ORDER BY id", (session_id,)
        )
        return [_compaction(r) for r in rows]

    def deactivate_compactions(self, ids: list[int]) -> None:
        """Mark the given compaction records inactive."""
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        self._write(f"UPDATE compactions SET active=0 WHERE id IN ({marks})", tuple(ids))

    # pins

    def add_pin(self, pin: Pin) -> Pin:
        """Insert a pin; an active pin with the same session and text is returned instead."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM pins WHERE session_id=? AND text=? AND active=1"
                " ORDER BY id LIMIT 1",
                (pin.session_id, pin.text),
            ).fetchone()
            if row is not None:
                return _pin(row)
            cur = self._conn.execute(
                "INSERT INTO pins (session_id, text, source, source_turn, confidence, active,"
                " created_at) VALUES (?,?,?,?,?,?,?)",
                (pin.session_id, pin.text, pin.source, pin.source_turn, pin.confidence,
                 int(pin.active), utcnow()),
            )
            self._conn.commit()
            return pin.model_copy(update={"id": int(cur.lastrowid)})

    def list_pins(self, session_id: str, active_only: bool = False) -> list[Pin]:
        """Pins of a session, ordered by id."""
        sql = "SELECT * FROM pins WHERE session_id=?" + (" AND active=1" if active_only else "")
        return [_pin(r) for r in self._rows(sql + " ORDER BY id", (session_id,))]

    def deactivate_pin(self, session_id: str, pin_id: int) -> bool:
        """Deactivate a pin; True only if a row in that session changed."""
        cur = self._write(
            "UPDATE pins SET active=0 WHERE id=? AND session_id=? AND active=1",
            (pin_id, session_id),
        )
        return cur.rowcount > 0

    # runs and episodes

    def insert_run(self, run: RunInfo) -> None:
        """Insert a run row (INSERT OR IGNORE)."""
        self._write(
            "INSERT OR IGNORE INTO runs (id, started_at, git_sha, config_json,"
            " model_hashes_json, seeds_json, args_json) VALUES (?,?,?,?,?,?,?)",
            (run.id, run.started_at, run.git_sha, _dumps(run.config),
             _dumps(run.model_hashes), _dumps(run.seeds), _dumps(run.args)),
        )

    def get_run(self, run_id: str) -> RunInfo | None:
        """Return the run or None."""
        rows = self._rows("SELECT * FROM runs WHERE id=?", (run_id,))
        if not rows:
            return None
        r = rows[0]
        return RunInfo(
            id=r["id"], started_at=r["started_at"], git_sha=r["git_sha"],
            config=json.loads(r["config_json"]),
            model_hashes=json.loads(r["model_hashes_json"]),
            seeds=json.loads(r["seeds_json"]), args=json.loads(r["args_json"]),
        )

    def episode_exists(
        self, run_id: str, scenario_id: str, model: str, condition: str, seed: int
    ) -> bool:
        """True if the episode's unique key already exists."""
        rows = self._rows(
            "SELECT EXISTS(SELECT 1 FROM episodes WHERE run_id=? AND scenario_id=?"
            " AND model=? AND condition=? AND seed=?) AS e",
            (run_id, scenario_id, model, condition, seed),
        )
        return bool(rows[0]["e"])

    def delete_errored_episodes(self, run_id: str) -> int:
        """Delete errored episodes of a run, and their session traces, so a resume retries them."""
        with self._lock:
            sids = [r["session_id"] for r in self._conn.execute(
                "SELECT session_id FROM episodes WHERE run_id=? AND error IS NOT NULL", (run_id,))]
            for sid in sids:
                for table, col in (("requests", "session_id"), ("compactions", "session_id"),
                                   ("pins", "session_id"), ("sessions", "id")):
                    self._conn.execute(f"DELETE FROM {table} WHERE {col}=?", (sid,))
            self._conn.execute(
                "DELETE FROM episodes WHERE run_id=? AND error IS NOT NULL", (run_id,))
            self._conn.commit()
            return len(sids)

    def insert_episode(self, ep: Episode) -> int:
        """Insert an episode and return its id."""
        cur = self._write(
            "INSERT INTO episodes (run_id, scenario_id, kind, model, condition, seed, violated,"
            " constraint_survived, summary_survived, task_done, validator_missing,"
            " auto_pins_total, auto_pins_tp, session_id, probe_json, error, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ep.run_id, ep.scenario_id, ep.kind, ep.model, ep.condition, ep.seed,
                int(ep.violated), _opt_int(ep.constraint_survived),
                _opt_int(ep.summary_survived), int(ep.task_done), ep.validator_missing,
                ep.auto_pins_total, ep.auto_pins_tp, ep.session_id, _dumps(ep.probe),
                ep.error, utcnow(),
            ),
        )
        return int(cur.lastrowid)

    def list_episodes(self, run_id: str) -> list[Episode]:
        """All episodes of a run, ordered by id."""
        rows = self._rows("SELECT * FROM episodes WHERE run_id=? ORDER BY id", (run_id,))
        return [
            Episode(
                run_id=r["run_id"], scenario_id=r["scenario_id"], kind=r["kind"],
                model=r["model"], condition=r["condition"], seed=r["seed"],
                session_id=r["session_id"], violated=bool(r["violated"]),
                task_done=bool(r["task_done"]),
                constraint_survived=_opt_bool(r["constraint_survived"]),
                summary_survived=_opt_bool(r["summary_survived"]),
                validator_missing=r["validator_missing"],
                auto_pins_total=r["auto_pins_total"], auto_pins_tp=r["auto_pins_tp"],
                probe=json.loads(r["probe_json"]), error=r["error"],
            )
            for r in rows
        ]

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Run a read-only query and return rows as dicts."""
        return [dict(r) for r in self._rows(sql, params)]
