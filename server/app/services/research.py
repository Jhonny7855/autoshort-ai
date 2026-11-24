"""Content research from free, public sources.

Every fetch is best-effort and rate-limited. Sources used:
  * Wikipedia REST API (CC BY-SA, attribution stored)
  * Google News RSS (headline discovery only, links retained)
  * Reddit public JSON endpoints (no auth, respects rate limits)
  * YouTube Data API (only when the user has a connected channel)

We never scrape pages that forbid it in robots.txt for content reuse; we store
short snippets for grounding plus the canonical link for the human to verify.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote_plus

import httpx

from ..config import settings
from ..db import log_event, query

UA = "AUTOSHORT-AI/1.0 (https://github.com/autoshort-ai; self-hosted local research tool)"
TIMEOUT = httpx.Timeout(12.0, connect=8.0)

WIKI_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _fix_text(text: str) -> str:
    """Repair mojibake that arrives from RSS feeds served as latin-1."""
    if not text:
        return ""
    repaired = text
    for src, dst in (("cp1252", "utf-8"), ("latin-1", "utf-8")):
        try:
            candidate = text.encode(src, errors="strict").decode(dst, errors="strict")
            if sum(1 for c in candidate if c == "\ufffd") <= text.count("\ufffd"):
                repaired = candidate
            break
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return repaired.replace("\ufffd", "'").strip()


async def wikipedia(topic: str, limit: int = 2) -> list[dict[str, Any]]:
    """Query the Wikipedia REST search API (no 403 on the action API)."""
    out: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=WIKI_HEADERS, follow_redirects=True) as client:
            r = await client.get(
                "https://en.wikipedia.org/w/rest.php/v1/search/page",
                params={"q": topic, "limit": limit, "language": "en"},
            )
            r.raise_for_status()
            pages = (r.json() or {}).get("pages") or []
            for item in pages[:limit]:
                title = _fix_text(item.get("title") or item.get("key") or "")
                snippet = _fix_text(_strip_tags(item.get("description") or item.get("excerpt") or ""))
                if not title:
                    continue
                summary = ""
                try:
                    s = await client.get(
                        f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote_plus(title.replace(' ', '_'))}"
                    )
                    if s.status_code == 200:
                        summary = _fix_text(s.json().get("extract") or "")
                except Exception:
                    pass
                out.append(
                    {
                        "title": title,
                        "url": f"https://en.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}",
                        "source_type": "wikipedia",
                        "snippet": (summary or snippet)[:900],
                    }
                )
    except Exception as exc:  # noqa: BLE001
        log_event("Wikipedia research failed", level="warn", scope="research", context={"error": str(exc)})
    return out


async def news(topic: str, limit: int = 3) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": UA}, follow_redirects=True) as client:
            r = await client.get(
                "https://news.google.com/rss/search",
                params={"q": topic, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            )
            r.raise_for_status()
            items = re.findall(r"<item>(.*?)</item>", r.text, flags=re.S)[:limit]
            for item in items:
                title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, flags=re.S)
                link = re.search(r"<link>(.*?)</link>", item, flags=re.S)
                pub = re.search(r"<pubDate>(.*?)</pubDate>", item, flags=re.S)
                if not title or not link:
                    continue
                out.append(
                    {
                        "title": _fix_text(_strip_tags(title.group(1)))[:200],
                        "url": link.group(1).strip(),
                        "source_type": "news_rss",
                        "snippet": _fix_text(_strip_tags(title.group(1)))[:400],
                        "published": (pub.group(1).strip() if pub else None),
                    }
                )
    except Exception as exc:  # noqa: BLE001
        log_event("News RSS research failed", level="warn", scope="research", context={"error": str(exc)})
    return out


async def reddit(topic: str, limit: int = 3) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": UA}, follow_redirects=True) as client:
            r = await client.get(
                "https://www.reddit.com/search.json",
                params={"q": topic, "sort": "relevance", "t": "month", "limit": limit},
            )
            if r.status_code != 200:
                return out
            for child in (r.json().get("data", {}).get("children") or [])[:limit]:
                d = child.get("data", {})
                out.append(
                    {
                        "title": _fix_text(d.get("title") or "")[:200],
                        "url": "https://www.reddit.com" + (d.get("permalink") or ""),
                        "source_type": "reddit",
                        "snippet": _fix_text(d.get("selftext") or d.get("title") or "")[:500],
                        "score": d.get("score"),
                    }
                )
    except Exception as exc:  # noqa: BLE001
        log_event("Reddit research failed", level="warn", scope="research", context={"error": str(exc)})
    return out


async def youtube_search(user_id: int, topic: str, limit: int = 3) -> list[dict[str, Any]]:
    from . import youtube

    token = await youtube.access_token_for(user_id)
    if not token:
        return []
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet",
                    "q": topic,
                    "type": "video",
                    "maxResults": limit,
                    "order": "viewCount",
                    "videoDuration": "short",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code != 200:
                return []
            items = r.json().get("items", [])
        return [
            {
                "title": (i.get("snippet", {}).get("title") or "")[:200],
                "url": f"https://www.youtube.com/watch?v={i['id']['videoId']}",
                "source_type": "youtube",
                "snippet": (i.get("snippet", {}).get("description") or "")[:400],
            }
            for i in items
            if i.get("id", {}).get("videoId")
        ]
    except Exception:
        return []


STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "about", "your", "you", "are",
    "was", "were", "has", "have", "how", "why", "what", "when", "where", "who", "will", "can",
    "its", "it", "of", "in", "on", "to", "a", "an", "is", "be", "as", "at", "by", "or", "our",
    "their", "they", "we", "us", "more", "most", "new", "all", "one", "two", "vs", "explained",
}


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def relevance(item: dict[str, Any], topic: str, angle: str = "") -> float:
    """Share of topic keywords the source title/snippet actually mentions.

    Search feeds happily return unrelated pages ("The Mighty Boosh series 2" for
    "the Milky Way"), and those pollute the script. Anything below the threshold
    is dropped before it can reach the writer.
    """
    wanted = _keywords(topic) | _keywords(angle)
    if not wanted:
        return 1.0
    haystack = _keywords(f"{item.get('title') or ''} {item.get('snippet') or ''}")
    if not haystack:
        return 0.0
    return len(wanted & haystack) / len(wanted)


MIN_RELEVANCE = 0.25


async def gather(
    user_id: int, topic: str, *, angle: str = "", include_youtube: bool = True
) -> list[dict[str, Any]]:
    tasks = [wikipedia(topic), news(topic), reddit(topic)]
    if include_youtube:
        tasks.append(youtube_search(user_id, topic))
    groups = await asyncio.gather(*tasks, return_exceptions=True)
    results: list[dict[str, Any]] = []
    for group in groups:
        if isinstance(group, list):
            results.extend(group)
    seen: set[str] = set()
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in results:
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        scored.append((relevance(item, topic, angle), item))

    kept = [item for score, item in scored if score >= MIN_RELEVANCE]
    # Do not over-trim: if the strict pass leaves too little grounding, add the
    # best partial matches (never zero-match feed noise, which is what derails
    # the script).
    if len(kept) < 2:
        for score, item in sorted(scored, key=lambda pair: pair[0], reverse=True):
            if len(kept) >= 2:
                break
            if score > 0 and item not in kept:
                kept.append(item)

    dropped = len(scored) - len(kept)
    if dropped:
        log_event(
            "Dropped off-topic research results",
            level="info",
            scope="research",
            context={"dropped": dropped, "kept": len(kept), "topic": topic[:120]},
        )
    return kept


def history_fingerprints(user_id: int) -> list[str]:
    rows = query(
        """SELECT fingerprint FROM content_ideas WHERE user_id=? AND fingerprint IS NOT NULL
           UNION SELECT fingerprint FROM topic_history WHERE user_id=?""",
        (user_id, user_id),
    )
    return [r["fingerprint"] for r in rows if r.get("fingerprint")]


def system_context() -> dict[str, str]:
    return {"user_agent": UA, "ffmpeg": settings.FFMPEG_BIN}
