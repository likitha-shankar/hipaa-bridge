"""Local SQLite token vault.

Maps deterministic tokens <-> original PHI values. Tokens are derived from
an HMAC of the normalized value, so the same patient name always yields the
same token across documents and sessions — referential consistency without
storing anything reversible outside this database.

The vault file and the HMAC secret stay on the local machine; together they
are the only way to re-identify text.
"""

from __future__ import annotations

import hmac
import hashlib
import os
import secrets
import sqlite3
import threading
from pathlib import Path

_TOKEN_HEX_LEN = 8  # 4 bytes of HMAC -> 8 hex chars; collisions extend length


class TokenVault:
    def __init__(self, db_path: str | Path = "hipaa_bridge_vault.db", secret: bytes | None = None):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS token_map (
                   token    TEXT PRIMARY KEY,
                   category TEXT NOT NULL,
                   value    TEXT NOT NULL,
                   created  TEXT NOT NULL DEFAULT (datetime('now'))
               )"""
        )
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_cat_value ON token_map (category, value)"
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"""
        )
        self._conn.commit()
        self._secret = secret or self._load_or_create_secret()

    def _load_or_create_secret(self) -> bytes:
        env = os.environ.get("HIPAA_BRIDGE_SECRET")
        if env:
            return env.encode()
        row = self._conn.execute("SELECT value FROM meta WHERE key='hmac_secret'").fetchone()
        if row:
            return bytes.fromhex(row[0])
        secret = secrets.token_bytes(32)
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('hmac_secret', ?)", (secret.hex(),)
            )
            self._conn.commit()
        return secret

    # --- tokenize ---------------------------------------------------------

    def tokenize(self, category: str, value: str) -> str:
        """Return the deterministic token for (category, value), storing the mapping."""
        normalized = " ".join(value.split())
        digest = hmac.new(
            self._secret, f"{category}|{normalized.lower()}".encode(), hashlib.sha256
        ).hexdigest().upper()

        with self._lock:
            row = self._conn.execute(
                "SELECT token FROM token_map WHERE category=? AND value=?",
                (category, normalized),
            ).fetchone()
            if row:
                return row[0]

            # Extend hex length on the (vanishingly rare) collision.
            for length in range(_TOKEN_HEX_LEN, len(digest) + 1, 4):
                token = f"[{category}_{digest[:length]}]"
                existing = self._conn.execute(
                    "SELECT value FROM token_map WHERE token=?", (token,)
                ).fetchone()
                if existing is None:
                    self._conn.execute(
                        "INSERT INTO token_map (token, category, value) VALUES (?, ?, ?)",
                        (token, category, normalized),
                    )
                    self._conn.commit()
                    return token
                if existing[0] == normalized:
                    return token
            raise RuntimeError("token space exhausted")  # unreachable in practice

    # --- lookup -------------------------------------------------------------

    def lookup(self, token: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM token_map WHERE token=?", (token,)
        ).fetchone()
        return row[0] if row else None

    def all_tokens(self) -> dict[str, str]:
        return dict(self._conn.execute("SELECT token, value FROM token_map").fetchall())

    def stats(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT category, COUNT(*) FROM token_map GROUP BY category"
        ).fetchall()
        return {category: count for category, count in rows}

    def close(self) -> None:
        self._conn.close()
