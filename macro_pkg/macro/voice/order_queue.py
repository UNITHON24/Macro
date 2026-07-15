from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class QueuedOrder:
    order_id: str
    items: Tuple[Dict[str, Any], ...]
    attempt: int
    status: str


class OrderQueue:
    """Durable fail-closed handoff for side-effecting kiosk orders.

    Claimed orders are never automatically replayed: after a crash their
    physical side effects are unknown and require an operator decision.
    """

    def __init__(self, path: str):
        self.path = str(Path(path).expanduser())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        with self._init_lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'queued', 'claimed', 'awaiting_handoff',
                        'succeeded', 'failed', 'uncertain'
                    )),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    claimed_at TEXT,
                    completed_at TEXT,
                    result TEXT
                )
                """
            )
            schema = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'orders'"
            ).fetchone()["sql"]
            if any(
                state not in str(schema)
                for state in ("uncertain", "awaiting_handoff")
            ):
                connection.execute("ALTER TABLE orders RENAME TO orders_legacy")
                connection.execute(
                    """
                    CREATE TABLE orders (
                        order_id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        status TEXT NOT NULL CHECK(status IN (
                            'queued', 'claimed', 'awaiting_handoff',
                            'succeeded', 'failed', 'uncertain'
                        )),
                        attempts INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        claimed_at TEXT,
                        completed_at TEXT,
                        result TEXT
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO orders SELECT * FROM orders_legacy"
                )
                connection.execute("DROP TABLE orders_legacy")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_orders_status_created "
                "ON orders(status, created_at)"
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _validate_items(items: Sequence[Dict[str, Any]]) -> Tuple[Dict[str, Any], ...]:
        if not isinstance(items, (list, tuple)) or not items:
            raise ValueError("order items are required")
        if not all(isinstance(item, dict) for item in items):
            raise ValueError("each order item must be an object")
        return tuple(dict(item) for item in items)

    def enqueue(
        self,
        items: Sequence[Dict[str, Any]],
        *,
        idempotency_key: Optional[str] = None,
    ) -> Tuple[str, bool, str]:
        normalized = self._validate_items(items)
        order_id = str(idempotency_key or uuid.uuid4()).strip()
        if not order_id or len(order_id) > 200:
            raise ValueError("invalid order id")
        payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload, status FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
            if existing is not None:
                if str(existing["payload"]) != payload:
                    raise ValueError(f"idempotency key collision: {order_id}")
                return order_id, False, str(existing["status"])
            cursor = connection.execute(
                "INSERT INTO orders "
                "(order_id, payload, status, created_at) VALUES (?, ?, 'queued', ?)",
                (order_id, payload, _now()),
            )
            created = cursor.rowcount == 1
            row = connection.execute(
                "SELECT status FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
        return order_id, created, str(row["status"])

    def claim_next(self) -> Optional[QueuedOrder]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            in_flight = connection.execute(
                "SELECT 1 FROM orders "
                "WHERE status IN ('claimed', 'awaiting_handoff', 'uncertain') LIMIT 1"
            ).fetchone()
            if in_flight is not None:
                connection.commit()
                return None
            row = connection.execute(
                "SELECT order_id, payload, attempts FROM orders "
                "WHERE status = 'queued' ORDER BY created_at, rowid LIMIT 1"
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            updated = connection.execute(
                "UPDATE orders SET status = 'claimed', claimed_at = ?, attempts = attempts + 1 "
                "WHERE order_id = ? AND status = 'queued'",
                (_now(), row["order_id"]),
            )
            if updated.rowcount != 1:
                connection.rollback()
                return None
            connection.commit()
        items = tuple(json.loads(row["payload"]))
        return QueuedOrder(str(row["order_id"]), items, int(row["attempts"]) + 1, "claimed")

    def complete(self, order_id: str, result: Dict[str, Any]) -> str:
        if bool(result.get("requires_manual_review")):
            destination = "uncertain"
        elif bool(result.get("awaiting_handoff")):
            destination = "awaiting_handoff"
        else:
            destination = "succeeded" if bool(result.get("success")) else "failed"
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
            if row is None:
                raise KeyError(order_id)
            current = str(row["status"])
            if current in {"awaiting_handoff", "succeeded", "failed", "uncertain"}:
                return current
            if current != "claimed":
                raise ValueError(f"order is not claimed: {order_id}")
            connection.execute(
                "UPDATE orders SET status = ?, completed_at = ?, result = ? "
                "WHERE order_id = ?",
                (destination, _now(), encoded, order_id),
            )
        return destination

    def status(self, order_id: str) -> Optional[str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
        return str(row["status"]) if row else None

    def list_orders(self, limit: int = 50) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT order_id, status, attempts, created_at, claimed_at, completed_at "
                "FROM orders ORDER BY created_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def resolve_uncertain(self, order_id: str, resolution: str) -> str:
        """Resolve an order only after the physical kiosk state was checked."""
        if resolution not in {"succeeded", "failed", "requeue"}:
            raise ValueError("resolution must be succeeded, failed, or requeue")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
            if row is None:
                raise KeyError(order_id)
            if row["status"] not in {"claimed", "awaiting_handoff", "uncertain"}:
                raise ValueError(f"order is not awaiting manual review: {order_id}")
            if resolution == "requeue":
                connection.execute(
                    "UPDATE orders SET status = 'queued', claimed_at = NULL WHERE order_id = ?",
                    (order_id,),
                )
                return "queued"
            result = json.dumps(
                {
                    "success": resolution == "succeeded",
                    "operator_resolved": True,
                },
                separators=(",", ":"),
            )
            connection.execute(
                "UPDATE orders SET status = ?, completed_at = ?, result = ? WHERE order_id = ?",
                (resolution, _now(), result, order_id),
            )
        return resolution
