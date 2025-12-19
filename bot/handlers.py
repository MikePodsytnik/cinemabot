from __future__ import annotations

import asyncio
from html import escape

import aiohttp
from aiohttp import ClientError
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .text import START, HELP
from .db import add_history, inc_stat, get_history, get_stats
from .watchlinks import find_first_watch_link
from .tmdb import tmdb_search_best, tmdb_fetch_details
from .cache import TTLCache, norm_query


def _format_html(meta, watch_url: str | None) -> str:
    title = escape(meta.title)
    year = f" ({escape(meta.year)})" if meta.year else ""
    rating = f"<b>Рейтинг:</b> {meta.rating:.1f}\n" if meta.rating is not None else ""

    overview = meta.overview or ""
    if len(overview) > 800:
        overview = overview[:800].rsplit(" ", 1)[0] + "…"
    overview_block = f"<b>Описание:</b> {escape(overview)}\n" if overview else ""

    link = (
        f"<b>Смотреть:</b> {escape(watch_url)}\n"
        if watch_url
        else "<b>Смотреть:</b> не нашёл рабочую ссылку\n"
    )
    return f"<b>{title}{year}</b>\n{rating}{overview_block}{link}"


def _build_ui(watch_url: str | None) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()

    if watch_url:
        kb.button(text="Смотреть", url=watch_url)

    kb.button(text="История", callback_data="ui:history")
    kb.button(text="Статистика", callback_data="ui:stats")

    if watch_url:
        kb.adjust(1, 2)
    else:
        kb.adjust(2)

    return kb


async def _send_history(message: Message, db_path: str, user_id: int) -> None:
    rows = await get_history(db_path, user_id, limit=10)
    if not rows:
        await message.answer("История пуста.")
        return

    lines = []
    for i, row in enumerate(rows, 1):
        t = row.ts.replace("T", " ").replace("+00:00", " UTC")
        title = row.title or "—"
        url = row.url or "—"
        lines.append(f"{i}) [{t}] запрос: {row.query}\n   фильм: {title}\n   ссылка: {url}")
    await message.answer("\n\n".join(lines))


async def _send_stats(message: Message, db_path: str, user_id: int) -> None:
    rows = await get_stats(db_path, user_id, limit=10)
    if not rows:
        await message.answer("Статистика пуста.")
        return

    lines = ["Топ по предложенным фильмам:"]
    for i, row in enumerate(rows, 1):
        lines.append(f"{i}) {row.title} — {row.count}")
    await message.answer("\n".join(lines))


def build_router(db_path: str, tmdb_api_key: str) -> Router:
    r = Router()

    meta_cache: TTLCache = TTLCache(ttl_seconds=30 * 60, maxsize=512)
    watch_cache: TTLCache = TTLCache(ttl_seconds=30 * 60, maxsize=1024)

    @r.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        await message.answer(START)

    @r.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(HELP)

    @r.message(Command("history"))
    async def cmd_history(message: Message) -> None:
        await _send_history(message, db_path, user_id=message.from_user.id)

    @r.message(Command("stats"))
    async def cmd_stats(message: Message) -> None:
        await _send_stats(message, db_path, user_id=message.from_user.id)

    @r.callback_query(F.data == "ui:history")
    async def cb_history(call: CallbackQuery) -> None:
        await call.answer()
        if call.message:
            await _send_history(call.message, db_path, user_id=call.from_user.id)

    @r.callback_query(F.data == "ui:stats")
    async def cb_stats(call: CallbackQuery) -> None:
        await call.answer()
        if call.message:
            await _send_stats(call.message, db_path, user_id=call.from_user.id)

    @r.message(F.text)
    async def on_query(message: Message) -> None:
        user_id = message.from_user.id
        user_query = (message.text or "").strip()
        if not user_query:
            return

        user_key = norm_query(user_query)

        meta = meta_cache.get(user_key)
        if meta is None:
            try:
                timeout = aiohttp.ClientTimeout(total=4.0)
                connector = aiohttp.TCPConnector(use_dns_cache=False)
                async with aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=False) as session:
                    meta = await tmdb_search_best(session, tmdb_api_key, user_query)
                    if meta:
                        detailed = await tmdb_fetch_details(session, tmdb_api_key, meta.media_type, meta.tmdb_id)
                        if detailed:
                            meta = detailed
                meta_cache.set(user_key, meta)
                if meta:
                    meta_cache.set(norm_query(meta.title), meta)
            except (ClientError, asyncio.TimeoutError):
                meta = None
                meta_cache.set(user_key, None)

        if not meta:
            await message.answer(f"К сожалению, по запросу «{user_query}» ничего не найдено.")
            return

        watch_url: str | None = None

        watch_key = f"tmdb:{meta.media_type}:{meta.tmdb_id}"
        cached_watch = watch_cache.get(watch_key)
        if cached_watch is None:
            q = meta.title
            if meta.year:
                q = f"{meta.title} {meta.year}"
            watch = await find_first_watch_link(q)
            watch_url = watch.url if watch else None
            watch_cache.set(watch_key, watch_url)
        else:
            watch_url = cached_watch

        title_for_stats = meta.title if meta else user_query

        await add_history(
            db_path,
            user_id,
            query=user_query,
            title=(meta.title if meta else None),
            url=watch_url,
        )
        await inc_stat(db_path, user_id, title_for_stats)

        kb = _build_ui(watch_url).as_markup()

        if not meta:
            if watch_url:
                await message.answer(f"{user_query}\nСмотреть: {watch_url}", reply_markup=kb)
            else:
                await message.answer(f"{user_query}\nМетаданные TMDb недоступны и ссылку не нашёл.", reply_markup=kb)
            return

        text = _format_html(meta, watch_url)
        if meta.poster_url:
            try:
                await message.answer_photo(
                    photo=meta.poster_url,
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb,
                )
                return
            except Exception:
                pass

        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    return r
