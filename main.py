from __future__ import annotations

import asyncio
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from bot.config import load_config
from bot.db import init_db
from bot.handlers import build_router


async def main() -> None:
    cfg = load_config()
    await init_db(cfg.db_path)

    bot = Bot(
        token=cfg.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(build_router(cfg.db_path, cfg.tmdb_api_key))

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
