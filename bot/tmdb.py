from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp

log = logging.getLogger("cinemabot.tmdb")

TMDB_DEBUG = os.getenv("TMDB_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}

@dataclass(frozen=True)
class MovieMeta:
    tmdb_id: int
    media_type: str
    title: str
    year: str | None
    overview: str | None
    rating: float | None
    poster_url: str | None


_TMDB_BASE = "https://api.themoviedb.org/3"
_IMG_BASE = "https://image.tmdb.org/t/p/w500"


def _pick_year(date_str: str | None) -> str | None:
    if not date_str:
        return None
    return date_str[:4] if len(date_str) >= 4 else None


def _poster_url(path: str | None) -> str | None:
    if not path:
        return None
    return f"{_IMG_BASE}{path}"


async def _read_text_safe(resp: aiohttp.ClientResponse, limit: int = 600) -> str:
    try:
        text = await resp.text(errors="ignore")
        text = " ".join(text.split())
        return text[:limit]
    except Exception:
        return ""


def _safe_url(url: str) -> str:
    return url


async def _search_multi(
    session: aiohttp.ClientSession,
    api_key: str,
    query: str,
    language: str,
) -> list[dict]:
    params = {
        "api_key": api_key,
        "query": query,
        "language": language,
        "include_adult": "false",
        "page": "1",
    }

    url = f"{_TMDB_BASE}/search/multi"
    t0 = time.perf_counter()
    try:
        async with session.get(url, params=params) as resp:
            dt_ms = (time.perf_counter() - t0) * 1000

            if TMDB_DEBUG:
                log.info("TMDB GET %s lang=%s status=%s time=%.0fms", _safe_url(url), language, resp.status, dt_ms)

            if resp.status >= 400:
                body = await _read_text_safe(resp)
                log.warning(
                    "TMDB search error status=%s lang=%s query=%r body=%r",
                    resp.status,
                    language,
                    query,
                    body,
                )
                return []

            data = await resp.json(content_type=None)

        results = data.get("results") or []
        if TMDB_DEBUG:
            log.info("TMDB results lang=%s query=%r count=%d", language, query, len(results))
        return results

    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        dt_ms = (time.perf_counter() - t0) * 1000
        log.warning("TMDB request failed lang=%s query=%r time=%.0fms err=%s", language, query, dt_ms, repr(e))
        return []
    except Exception as e:
        dt_ms = (time.perf_counter() - t0) * 1000
        log.exception("TMDB unexpected error lang=%s query=%r time=%.0fms err=%s", language, query, dt_ms, repr(e))
        return []


def _pick_first_movie_tv(results: list[dict], query_fallback: str) -> Optional[MovieMeta]:
    for r in results:
        mt = r.get("media_type")
        if mt not in ("movie", "tv"):
            continue

        tmdb_id = r.get("id")
        if not isinstance(tmdb_id, int):
            continue

        title = r.get("title") if mt == "movie" else r.get("name")
        if not title:
            title = query_fallback

        date = r.get("release_date") if mt == "movie" else r.get("first_air_date")
        year = _pick_year(date)

        overview = r.get("overview") or None
        rating = r.get("vote_average")
        rating = float(rating) if isinstance(rating, (int, float)) else None

        poster = _poster_url(r.get("poster_path"))

        return MovieMeta(
            tmdb_id=tmdb_id,
            media_type=mt,
            title=str(title),
            year=year,
            overview=str(overview) if overview else None,
            rating=rating,
            poster_url=poster,
        )
    return None


async def tmdb_search_best(
    session: aiohttp.ClientSession,
    api_key: str,
    query: str,
) -> Optional[MovieMeta]:
    ru = await _search_multi(session, api_key, query, language="ru-RU")
    meta = _pick_first_movie_tv(ru, query)
    if meta:
        if TMDB_DEBUG:
            log.info("TMDB picked RU: %s (%s) id=%s type=%s", meta.title, meta.year, meta.tmdb_id, meta.media_type)
        return meta

    en = await _search_multi(session, api_key, query, language="en-US")
    meta2 = _pick_first_movie_tv(en, query)
    if TMDB_DEBUG and meta2:
        log.info("TMDB picked EN: %s (%s) id=%s type=%s", meta2.title, meta2.year, meta2.tmdb_id, meta2.media_type)
    return meta2


async def tmdb_fetch_details(
    session: aiohttp.ClientSession,
    api_key: str,
    media_type: str,
    tmdb_id: int,
) -> Optional[MovieMeta]:
    url = f"{_TMDB_BASE}/{media_type}/{tmdb_id}"
    params = {"api_key": api_key, "language": "ru-RU"}

    t0 = time.perf_counter()
    try:
        async with session.get(url, params=params) as resp:
            dt_ms = (time.perf_counter() - t0) * 1000
            if TMDB_DEBUG:
                log.info("TMDB GET %s status=%s time=%.0fms", _safe_url(url), resp.status, dt_ms)

            if resp.status >= 400:
                body = await _read_text_safe(resp)
                log.warning("TMDB details error status=%s id=%s type=%s body=%r", resp.status, tmdb_id, media_type, body)
                return None

            r = await resp.json(content_type=None)

        title = r.get("title") if media_type == "movie" else r.get("name")
        date = r.get("release_date") if media_type == "movie" else r.get("first_air_date")

        meta = MovieMeta(
            tmdb_id=tmdb_id,
            media_type=media_type,
            title=str(title) if title else str(tmdb_id),
            year=_pick_year(date),
            overview=r.get("overview") or None,
            rating=float(r["vote_average"]) if isinstance(r.get("vote_average"), (int, float)) else None,
            poster_url=_poster_url(r.get("poster_path")),
        )
        if TMDB_DEBUG:
            log.info("TMDB details ok: %s (%s) id=%s type=%s", meta.title, meta.year, meta.tmdb_id, meta.media_type)
        return meta

    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        dt_ms = (time.perf_counter() - t0) * 1000
        log.warning("TMDB details failed id=%s type=%s time=%.0fms err=%s", tmdb_id, media_type, dt_ms, repr(e))
        return None
    except Exception as e:
        dt_ms = (time.perf_counter() - t0) * 1000
        log.exception("TMDB details unexpected id=%s type=%s time=%.0fms err=%s", tmdb_id, media_type, dt_ms, repr(e))
        return None
