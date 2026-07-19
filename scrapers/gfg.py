import httpx
import json
import logging
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Optional
from .base import ScrapeResponse, CalendarInfo, HeatmapDay

logger = logging.getLogger(__name__)

API_URL = "https://practiceapi.geeksforgeeks.org/api/v1/user/problems/submissions/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Origin": "https://www.geeksforgeeks.org",
    "Referer": "https://www.geeksforgeeks.org/",
}

DIFFICULTY_MAP = {
    "School": "school",
    "Basic": "basic",
    "Easy": "easy",
    "Medium": "medium",
    "Hard": "hard",
}

# Weights for Coding Score calculation
WEIGHTS = {
    "basic": 1,
    "easy": 2,
    "medium": 4,
    "hard": 8,
    "school": 0,
}


async def scrape(handle: str) -> ScrapeResponse:
    print(f"\n[GFG] Fetching data for: {handle}")

    # --- 1. Fetch Submissions API ---
    api_data = await _fetch_submissions_api(handle)
    if not api_data:
        return ScrapeResponse(
            platform="gfg",
            handle=handle,
            error="Failed to fetch data from GFG API"
        )

    # --- 2. Extract data ---
    difficulty_counts = api_data.get("difficulty_counts", {})
    solved_questions = api_data.get("solved_questions_by_category", {})
    max_streak_lifetime = api_data.get("max_streak_lifetime", 0)
    max_streak_current_year = api_data.get("max_streak_current_year", 0)
    active_days = api_data.get("active_days", 0)
    heatmap_data = api_data.get("heatmap_data", [])

    # --- 3. Calculate Total Solved = Sum of all difficulty counts ---
    total_solved = sum(difficulty_counts.values())

    # --- 4. Calculate Coding Score using weights ---
    coding_score = 0
    for diff, count in difficulty_counts.items():
        weight = WEIGHTS.get(diff, 0)
        coding_score += count * weight

    print(f"[GFG] Difficulty Counts: {difficulty_counts}")
    print(f"[GFG] Total Solved (sum): {total_solved}")
    print(f"[GFG] Calculated Coding Score: {coding_score}")
    print(f"[GFG] Streaks: Lifetime={max_streak_lifetime}, CurrentYear={max_streak_current_year}")

    # --- 5. Build Response ---
    return ScrapeResponse(
        platform="gfg",
        handle=handle,
        total_solved=total_solved,
        rating=coding_score,
        contest_given=None,
        difficulty_counts=difficulty_counts if difficulty_counts else {},
        max_streak_lifetime=max_streak_lifetime,
        max_streak_current_year=max_streak_current_year,
        active_days=active_days,
        calendar_info=CalendarInfo(total_active_days=active_days, badges=[]),
        solved_questions_by_category=solved_questions if solved_questions else {},
        heatmap_data=heatmap_data if heatmap_data else []
    )


async def _fetch_submissions_api(handle: str) -> dict:
    """Fetch submissions API and extract difficulty counts, solved questions, and heatmap."""
    payload = {"handle": handle, "requestType": "", "year": "", "month": ""}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(API_URL, json=payload, headers=HEADERS)
            if resp.status_code != 200:
                print(f"[GFG API] Error: HTTP {resp.status_code}")
                return {}
            data = resp.json()
            if data.get("status") != "success":
                print(f"[GFG API] Status not success: {data.get('message')}")
                return {}
            result = data.get("result", {})
            if not result:
                print("[GFG API] No result data")
                return {}

            print(f"[GFG API] Found difficulties: {list(result.keys())}")

            # Initialize data structures
            solved_by_category = defaultdict(list)
            difficulty_counts = defaultdict(int)
            date_counts = defaultdict(int)
            seen_problems = set()  # For deduping solved questions list

            for gfg_diff, submissions in result.items():
                diff = DIFFICULTY_MAP.get(gfg_diff, gfg_diff.lower())
                if diff not in ["school", "basic", "easy", "medium", "hard"]:
                    continue
                for sub_id, sub_data in submissions.items():
                    pname = sub_data.get("pname")
                    if not pname:
                        continue
                    # Deduplicate by problem name + difficulty
                    problem_key = f"{diff}_{pname}"
                    if problem_key in seen_problems:
                        continue
                    seen_problems.add(problem_key)

                    # Add to category list
                    solved_by_category[diff].append(pname)
                    difficulty_counts[diff] += 1

                    # Extract submission date for heatmap
                    sub_time = sub_data.get("user_subtime")
                    if sub_time:
                        try:
                            dt = datetime.strptime(sub_time, "%Y-%m-%d %H:%M:%S").date()
                            date_counts[dt] += 1
                        except ValueError:
                            pass

            # Calculate streaks from date_counts
            max_streak_lifetime = 0
            max_streak_current_year = 0
            active_days = len(date_counts)
            current_year = datetime.now().year
            heatmap_data = []

            if date_counts:
                sorted_dates = sorted(date_counts.keys())
                heatmap_data = [HeatmapDay(date=d.isoformat(), count=date_counts[d]) for d in sorted_dates]

                # Lifetime Streak
                current_streak = 0
                prev_date = None
                for d in sorted_dates:
                    if prev_date is None:
                        current_streak = 1
                    elif (d - prev_date).days == 1:
                        current_streak += 1
                    else:
                        current_streak = 1
                    max_streak_lifetime = max(max_streak_lifetime, current_streak)
                    prev_date = d

                # Current Year (2026) Streak
                current_streak = 0
                prev_date = None
                for d in sorted_dates:
                    if d.year == current_year:
                        if prev_date is None:
                            current_streak = 1
                        elif (d - prev_date).days == 1:
                            current_streak += 1
                        else:
                            current_streak = 1
                        max_streak_current_year = max(max_streak_current_year, current_streak)
                        prev_date = d
                    else:
                        current_streak = 0
                        prev_date = None

            return {
                "solved_questions_by_category": dict(solved_by_category),
                "difficulty_counts": dict(difficulty_counts),
                "max_streak_lifetime": max_streak_lifetime,
                "max_streak_current_year": max_streak_current_year,
                "active_days": active_days,
                "heatmap_data": heatmap_data
            }

    except Exception as e:
        print(f"[GFG API] Error: {e}")
        return {}