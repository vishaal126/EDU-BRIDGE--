"""Database access layer. SQLite by default; PostgreSQL when DATABASE_URL is set.

All callers use '?' placeholders; they are converted for PostgreSQL automatically.
"""
import os
import re
import sqlite3
from datetime import datetime, timezone

import config
from models import SCHEMA


class DatabaseError(Exception):
    """Raised for any database failure, with a user-presentable message."""


class IntegrityViolation(DatabaseError):
    """Unique / foreign-key / check constraint failed."""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _db_url() -> str:
    return config.get("DATABASE_URL", "")


def is_postgres() -> bool:
    return _db_url().startswith(("postgres://", "postgresql://"))


def _sqlite_path() -> str:
    path = config.get("DATABASE_PATH", "data/edubridge.db")
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    return path


def _connect():
    try:
        if is_postgres():
            import psycopg2
            import psycopg2.extras

            url = _db_url().replace("postgres://", "postgresql://", 1)
            return psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
        conn = sqlite3.connect(_sqlite_path(), timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn
    except Exception as exc:  # connection failures surface as a friendly error
        raise DatabaseError("Could not connect to the database. Please try again shortly.") from exc


def _prep(sql: str) -> str:
    return re.sub(r"\?", "%s", sql) if is_postgres() else sql


def _is_integrity(exc: Exception) -> bool:
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    try:
        import psycopg2

        return isinstance(exc, psycopg2.IntegrityError)
    except ImportError:
        return False


def _run(sql: str, params=(), mode="none"):
    conn = _connect()
    try:
        cur = conn.cursor()
        sql = _prep(sql)
        if mode == "insert" and is_postgres():
            sql += " RETURNING id"
        cur.execute(sql, tuple(params))
        if mode == "all":
            result = [dict(r) for r in cur.fetchall()]
        elif mode == "one":
            row = cur.fetchone()
            result = dict(row) if row else None
        elif mode == "insert":
            result = cur.fetchone()["id"] if is_postgres() else cur.lastrowid
        else:
            result = cur.rowcount
        conn.commit()
        return result
    except DatabaseError:
        raise
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        if _is_integrity(exc):
            raise IntegrityViolation("That record already exists or is invalid.") from exc
        raise DatabaseError("A database error occurred. Please try again.") from exc
    finally:
        conn.close()


def query(sql, params=()):
    return _run(sql, params, "all")


def query_one(sql, params=()):
    return _run(sql, params, "one")


def execute(sql, params=()):
    return _run(sql, params, "none")


def insert(sql, params=()):
    return _run(sql, params, "insert")


def init_db() -> None:
    """Create all tables if they do not exist (idempotent)."""
    pk = "SERIAL PRIMARY KEY" if is_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"
    for stmt in SCHEMA:
        stmt = stmt.replace("{PK}", pk)
        if is_postgres():
            stmt = stmt.replace("BLOB", "BYTEA")
        _run(stmt)
