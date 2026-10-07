"""Persistent conversation state and interaction history for WhatsApp users."""

import json
import sqlite3
from contextlib import closing, contextmanager
from typing import Any, Dict

from src.config import SESSION_DB_PATH


@contextmanager
def _connection():
    SESSION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(SESSION_DB_PATH, timeout=10)) as connection, connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                phone TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY,
                phone TEXT NOT NULL,
                direction TEXT NOT NULL,
                message_sid TEXT,
                text TEXT NOT NULL,
                step TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(message_sid)
            )
        """)
        yield connection


def get_session(phone: str) -> Dict[str, Any]:
    with _connection() as connection:
        row = connection.execute(
            "SELECT data FROM sessions WHERE phone = ?", (phone,)
        ).fetchone()
    return json.loads(row[0]) if row else {"step": "idle"}


def update_session(phone: str, data: dict):
    with _connection() as connection:
        row = connection.execute(
            "SELECT data FROM sessions WHERE phone = ?", (phone,)
        ).fetchone()
        session = json.loads(row[0]) if row else {"step": "idle"}
        session.update(data)
        connection.execute(
            "INSERT OR REPLACE INTO sessions (phone, data) VALUES (?, ?)",
            (phone, json.dumps(session)),
        )


def clear_session(phone: str):
    with _connection() as connection:
        connection.execute("DELETE FROM sessions WHERE phone = ?", (phone,))


def record_interaction(
    phone: str, direction: str, text: str, step: str, message_sid: str = None
) -> bool:
    """Return False when an incoming Twilio message has already been claimed."""
    with _connection() as connection:
        cursor = connection.execute(
            """INSERT INTO interactions (phone, direction, message_sid, text, step)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(message_sid) DO NOTHING""",
            (phone, direction, message_sid or None, text, step),
        )
        return cursor.rowcount == 1


def get_interactions(phone: str) -> list:
    with _connection() as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM interactions WHERE phone = ? ORDER BY id", (phone,)
        ).fetchall()
    return [dict(row) for row in rows]
