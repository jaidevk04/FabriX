"""Local SQLite persistence with atomic simulated command/state commits."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Literal

from cognition.domain import Contract, Incident, State, now

Table = Literal[
    "plants",
    "incidents",
    "commands",
    "manifests",
    "capabilities",
    "automation",
    "specialists",
    "observations",
    "world_events",
    "business_state",
    "missions",
    "core_reports",
    "core_config",
    "action_orders",
    "kpi_samples",
    "impact_ledger",
    "work_orders",
    "recommendations",
]


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        for table in (
            "plants",
            "incidents",
            "commands",
            "manifests",
            "capabilities",
            "automation",
            "specialists",
            "observations",
            "world_events",
            "business_state",
            "missions",
            "core_reports",
            "core_config",
            "action_orders",
            "kpi_samples",
            "impact_ledger",
            "work_orders",
            "recommendations",
        ):
            self.db.execute(f"CREATE TABLE IF NOT EXISTS {table}(id TEXT PRIMARY KEY, body TEXT)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS audit("
            "seq INTEGER PRIMARY KEY, incident_id TEXT, kind TEXT, body TEXT, time TEXT)"
        )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def get(self, table: Table, key: str) -> str:
        with self.lock:
            row = self.db.execute(f"SELECT body FROM {table} WHERE id=?", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return row[0]

    def put(self, table: Table, key: str, value: Contract, *, create: bool = False) -> None:
        sql = f"INSERT INTO {table} VALUES (?,?)"
        if not create:
            sql += " ON CONFLICT(id) DO UPDATE SET body=excluded.body"
        with self.transaction() as db:
            db.execute(sql, (key, value.model_dump_json()))

    def plant(self, key: str) -> State:
        return State.model_validate_json(self.get("plants", key))

    def plants(self) -> list[State]:
        with self.lock:
            rows = self.db.execute("SELECT body FROM plants ORDER BY id").fetchall()
        return [State.model_validate_json(row[0]) for row in rows]

    def incidents(self) -> list[Incident]:
        with self.lock:
            rows = self.db.execute("SELECT body FROM incidents ORDER BY rowid DESC").fetchall()
        return [Incident.model_validate_json(row[0]) for row in rows]

    def records(self, table: Table) -> list[dict]:
        with self.lock:
            rows = self.db.execute(f"SELECT body FROM {table} ORDER BY id").fetchall()
        return [json.loads(row[0]) for row in rows]

    def audit(self, incident: str, kind: str, body: dict) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO audit(incident_id,kind,body,time) VALUES (?,?,?,?)",
                (incident, kind, json.dumps(body), now().isoformat()),
            )

    def events(self, incident: str, after: int = 0) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT seq,kind,body,time FROM audit WHERE incident_id=? AND seq>? ORDER BY seq",
                (incident, after),
            ).fetchall()
        return [dict(seq=r[0], kind=r[1], body=json.loads(r[2]), time=r[3]) for r in rows]

    def close(self) -> None:
        self.db.close()
