from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp
from ddgs import DDGS


@dataclass(frozen=True)
class WatchLink:
    url: str
    domain: str


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def search_candidates_sync(query: str, per_domain: int) -> list[str]:
    urls: list[str] = []
    with DDGS() as ddgs:
        q = f'lordfilm "{query}" смотреть онлайн бесплатно'
        for r in ddgs.text(q, max_results=per_domain):
            url = (r.get("href") or r.get("url") or "").strip()
            if url.startswith(("http://", "https://")):
                urls.append(url)

    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    print(out)
    return out


async def _is_working(session: aiohttp.ClientSession, url: str) -> WatchLink | None:
    host = _host(url)
    if not host:
        return None

    try:
        async with session.get(url, allow_redirects=True) as resp:
            if not (200 <= resp.status < 400):
                return None

            final_host = _host(str(resp.url))
            if not final_host:
                return None

            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "text/html" not in ctype:
                return None

            text = await resp.text(errors="ignore")

            return WatchLink(url=str(resp.url), domain=final_host)
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None


async def find_first_watch_link(
    query: str,
    *,
    per_domain: int = 4,
    total_limit: int = 20,
    concurrency: int = 8,
    timeout_s: float = 3.5,
) -> WatchLink | None:
    loop = asyncio.get_running_loop()
    candidates = await loop.run_in_executor(None, search_candidates_sync, query, per_domain)
    print(candidates)
    candidates = candidates[:total_limit]
    if not candidates:
        return None

    timeout = aiohttp.ClientTimeout(total=timeout_s)
    connector = aiohttp.TCPConnector(limit=concurrency, ssl=False)

    sem = asyncio.Semaphore(concurrency)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=False) as session:
        async def check(u: str):
            async with sem:
                return await _is_working(session, u)

        tasks = [asyncio.create_task(check(u)) for u in candidates]
        for done in asyncio.as_completed(tasks):
            res = await done
            print(res)
            if res is not None:
                for t in tasks:
                    t.cancel()
                return res

    return None