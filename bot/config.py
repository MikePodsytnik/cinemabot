from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    tmdb_api_key: str
    db_path: str


def load_config() -> Config:
    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is required")

    tmdb_api_key = os.getenv("TMDB_API_KEY", "").strip()
    if not tmdb_api_key:
        raise RuntimeError("TMDB_API_KEY is required")

    raw_db_path = os.getenv("DB_PATH", "bot.db").strip()
    project_root = Path(__file__).resolve().parents[1]
    db_path = Path(raw_db_path)
    if not db_path.is_absolute():
        db_path = project_root / db_path

    db_path.parent.mkdir(parents=True, exist_ok=True)

    return Config(
        bot_token=bot_token,
        tmdb_api_key=tmdb_api_key,
        db_path=str(db_path),
    )
