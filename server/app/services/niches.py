"""Niche catalogue plus AI-assisted scoring."""
from __future__ import annotations

import json
from typing import Any

from ..db import execute, insert, query, query_one, utcnow
from . import ai

PRESET_NICHES: list[dict[str, Any]] = [
    {
        "slug": "ai-technology",
        "name": "AI & Technology",
        "description": "Explainers on artificial intelligence, tools, and the near future of tech.",
        "audience": "Curious 18-40 tech enthusiasts",
        "visual_style": "neon circuits, product renders, abstract data",
        "visual_score": 9.2,
    },
    {
        "slug": "interesting-facts",
        "name": "Interesting Facts",
        "description": "Surprising, verifiable facts delivered fast.",
        "audience": "Broad mobile audience 16-45",
        "visual_style": "bold typography, archival imagery",
        "visual_score": 8.6,
    },
    {
        "slug": "history",
        "name": "History",
        "description": "Dramatic micro-stories from the past with real sources.",
        "audience": "History buffs and students",
        "visual_style": "engravings, parchment, muted cinematic",
        "visual_score": 8.1,
    },
    {
        "slug": "science",
        "name": "Science",
        "description": "Physics, biology and chemistry explained in under a minute.",
        "audience": "Students and science-curious adults",
        "visual_style": "macro shots, diagrams, particle FX",
        "visual_score": 8.8,
    },
    {
        "slug": "space",
        "name": "Space",
        "description": "Astronomy, missions and cosmic scale comparisons.",
        "audience": "Space fans 15-45",
        "visual_style": "nebula gradients, orbital renders",
        "visual_score": 9.4,
    },
    {
        "slug": "gaming",
        "name": "Gaming",
        "description": "Game mechanics, industry stories and speedrun trivia.",
        "audience": "Gamers 13-30",
        "visual_style": "gameplay crops, HUD overlays, neon",
        "visual_score": 8.0,
    },
    {
        "slug": "motivation",
        "name": "Motivation",
        "description": "Short disciplined pep talks with practical framing.",
        "audience": "Self-improvement seekers",
        "visual_style": "silhouettes, sunrise gradients, slow push-ins",
        "visual_score": 7.4,
    },
    {
        "slug": "finance-education",
        "name": "Finance Education",
        "description": "Money mechanics explained plainly, no hype.",
        "audience": "Young adults learning money basics",
        "visual_style": "clean charts, tickers, minimal icons",
        "visual_score": 7.2,
    },
    {
        "slug": "business",
        "name": "Business",
        "description": "How companies really work, in 60 seconds.",
        "audience": "Founders, students, operators",
        "visual_style": "editorial photography, brand cards",
        "visual_score": 7.6,
    },
    {
        "slug": "psychology",
        "name": "Psychology",
        "description": "Behaviour, bias and brain tricks you can test today.",
        "audience": "Curious adults 18-40",
        "visual_style": "portraits, optical illusions, soft gradients",
        "visual_score": 8.2,
    },
    {
        "slug": "mystery",
        "name": "Mystery",
        "description": "Unsolved cases and unexplained events, carefully sourced.",
        "audience": "Mystery and true-crime adjacent audiences",
        "visual_style": "low light, film grain, slow reveal",
        "visual_score": 8.5,
    },
    {
        "slug": "animals",
        "name": "Animals",
        "description": "Wildlife behaviour and weird biology.",
        "audience": "All ages",
        "visual_style": "macro wildlife, natural colour",
        "visual_score": 9.0,
    },
    {
        "slug": "geography",
        "name": "Geography",
        "description": "Borders, maps and place-based surprises.",
        "audience": "Map lovers and students",
        "visual_style": "map animations, satellite imagery",
        "visual_score": 8.4,
    },
    {
        "slug": "cricket",
        "name": "Cricket",
        "description": "Records, tactics and moments from cricket history.",
        "audience": "Cricket fans (South Asia heavy)",
        "visual_style": "stadium crops, scorecard cards",
        "visual_score": 7.8,
    },
    {
        "slug": "movies",
        "name": "Movies",
        "description": "Filmmaking choices explained without spoilers-by-default.",
        "audience": "Film fans 18-40",
        "visual_style": "letterboxed stills, colour-grade comparisons",
        "visual_score": 7.9,
    },
    {
        "slug": "education",
        "name": "Education",
        "description": "Exam-friendly explainers across subjects.",
        "audience": "Students 15-25",
        "visual_style": "whiteboard, diagrams, clean cards",
        "visual_score": 7.0,
    },
    {
        "slug": "storytelling",
        "name": "Storytelling",
        "description": "Tight original micro-fiction with a twist.",
        "audience": "Short-fiction listeners",
        "visual_style": "cinematic stills, mood lighting",
        "visual_score": 8.3,
    },
    {
        "slug": "horror-stories",
        "name": "Horror Stories",
        "description": "Original short horror, clearly labelled as fiction.",
        "audience": "Horror fans 16+",
        "visual_style": "dark corridors, grain, red accents",
        "visual_score": 8.7,
    },
    {
        "slug": "travel",
        "name": "Travel",
        "description": "Places, costs and practical tips.",
        "audience": "Travellers and planners",
        "visual_style": "aerial footage, warm grade",
        "visual_score": 8.9,
    },
    {
        "slug": "coding",
        "name": "Coding",
        "description": "Programming concepts and tooling, fast.",
        "audience": "Developers and CS students",
        "visual_style": "editor screenshots, terminal, syntax colour",
        "visual_score": 7.1,
    },
]

SCORING_WEIGHTS = {
    "demand_score": 0.22,
    "competition_score": -0.12,
    "shorts_fit_score": 0.20,
    "repeatability_score": 0.14,
    "difficulty_score": -0.08,
    "monetization_score": 0.10,
    "evergreen_score": 0.12,
    "visual_score": 0.12,
}


def compute_total(row: dict[str, Any]) -> float:
    total = 50.0
    for key, weight in SCORING_WEIGHTS.items():
        value = row.get(key)
        if value is None:
            continue
        total += (float(value) - 5.0) * 10 * weight
    return round(max(0.0, min(100.0, total)), 1)


def ensure_presets(user_id: int) -> None:
    existing = {r["slug"] for r in query("SELECT slug FROM niches WHERE user_id=?", (user_id,))}
    for preset in PRESET_NICHES:
        if preset["slug"] in existing:
            continue
        row = {
            "user_id": user_id,
            "slug": preset["slug"],
            "name": preset["name"],
            "description": preset["description"],
            "audience": preset["audience"],
            "visual_style": preset["visual_style"],
            "demand_score": 7.0,
            "competition_score": 6.0,
            "shorts_fit_score": 8.0,
            "repeatability_score": 8.0,
            "difficulty_score": 4.0,
            "monetization_score": 6.5,
            "evergreen_score": 7.5,
            "visual_score": preset["visual_score"],
            "source": "preset",
            "active": 0,
            "created_at": utcnow(),
        }
        row["total_score"] = compute_total(row)
        insert("niches", row)


async def score_niches(user_id: int) -> list[dict[str, Any]]:
    """Ask the local model to score preset niches; falls back to heuristic totals."""
    ensure_presets(user_id)
    rows = query("SELECT * FROM niches WHERE user_id=? ORDER BY name", (user_id,))
    names = [r["name"] for r in rows]
    prompt = (
        "You evaluate YouTube Shorts niches. Score each niche 1-10 on: demand_score, "
        "competition_score (10 = saturated), shorts_fit_score, repeatability_score, "
        "difficulty_score (10 = very hard to produce), monetization_score, evergreen_score, "
        "visual_score. Also return 'rationale' (one sentence) and 'audience'.\n"
        f"Niches: {json.dumps(names)}\n"
        'Reply with JSON: {"niches":[{"name":str,"demand_score":num,"competition_score":num,'
        '"shorts_fit_score":num,"repeatability_score":num,"difficulty_score":num,'
        '"monetization_score":num,"evergreen_score":num,"visual_score":num,'
        '"rationale":str,"audience":str}]}'
    )
    try:
        raw = await ai.generate(prompt, system="You are a precise analytics engine. Output JSON only.", json_mode=True, temperature=0.4)
        data = ai.extract_json(raw)
        by_name = {str(n.get("name", "")).strip().lower(): n for n in data.get("niches", [])}
    except Exception:
        by_name = {}

    out = []
    for row in rows:
        patch: dict[str, Any] = {}
        ai_row = by_name.get(row["name"].strip().lower())
        if ai_row:
            for key in SCORING_WEIGHTS:
                try:
                    value = float(ai_row.get(key))
                except (TypeError, ValueError):
                    continue
                patch[key] = max(1.0, min(10.0, value))
            if ai_row.get("rationale"):
                patch["rationale"] = str(ai_row["rationale"])[:900]
            if ai_row.get("audience"):
                patch["audience"] = str(ai_row["audience"])[:200]
        merged = {**row, **patch}
        patch["total_score"] = compute_total(merged)
        if patch:
            assignments = ", ".join(f"{k}=?" for k in patch)
            execute(f"UPDATE niches SET {assignments} WHERE id=?", (*patch.values(), row["id"]))
        out.append({**merged, **patch})
    out.sort(key=lambda r: r.get("total_score") or 0, reverse=True)
    return out


def active_niche(user_id: int) -> dict[str, Any] | None:
    return query_one("SELECT * FROM niches WHERE user_id=? AND active=1", (user_id,))


def set_active(user_id: int, niche_id: int) -> dict[str, Any]:
    row = query_one("SELECT * FROM niches WHERE id=? AND user_id=?", (niche_id, user_id))
    if not row:
        raise ValueError("Niche not found")
    execute("UPDATE niches SET active=0 WHERE user_id=?", (user_id,))
    execute("UPDATE niches SET active=1 WHERE id=?", (niche_id,))
    return {**row, "active": 1}
