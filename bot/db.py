from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite


@dataclass(frozen=True)
class HistoryRow:
    ts: str
    query: str
    title: str | None
    url: str | None


@dataclass(frozen=True)
class StatRow:
    title: str
    count: int


def _resolve_db_path(db_path: str) -> str:
    p = Path(db_path).expanduser()
    if not p.is_absolute():
        project_root = Path(__file__).resolve().parents[1]
        p = project_root / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def init_db(db_path: str) -> None:
    db_path = _resolve_db_path(db_path)
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ts TEXT NOT NULL,
            query TEXT NOT NULL,
            title TEXT,
            url TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            count INTEGER NOT NULL,
            PRIMARY KEY (user_id, title)
        )
        """)
        await db.commit()


async def add_history(db_path: str, user_id: int, query: str, title: str | None, url: str | None) -> None:
    db_path = _resolve_db_path(db_path)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO history(user_id, ts, query, title, url) VALUES(?, ?, ?, ?, ?)",
            (user_id, _now_iso(), query, title, url),
        )
        await db.commit()


async def inc_stat(db_path: str, user_id: int, title: str) -> None:
    db_path = _resolve_db_path(db_path)
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
        INSERT INTO stats(user_id, title, count) VALUES(?, ?, 1)
        ON CONFLICT(user_id, title) DO UPDATE SET count = count + 1
        """, (user_id, title))
        await db.commit()


async def get_history(db_path: str, user_id: int, limit: int = 10) -> list[HistoryRow]:
    db_path = _resolve_db_path(db_path)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT ts, query, title, url FROM history WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        rows = await cur.fetchall()
    return [HistoryRow(ts=r["ts"], query=r["query"], title=r["title"], url=r["url"]) for r in rows]


async def get_stats(db_path: str, user_id: int, limit: int = 10) -> list[StatRow]:
    db_path = _resolve_db_path(db_path)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT title, count FROM stats WHERE user_id=? ORDER BY count DESC, title ASC LIMIT ?",
            (user_id, limit),
        )
        rows = await cur.fetchall()
    return [StatRow(title=r["title"], count=int(r["count"])) for r in rows]
