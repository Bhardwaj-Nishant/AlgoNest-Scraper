import httpx
import logging
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Any, Tuple
from .base import ScrapeResponse, CalendarInfo, HeatmapDay

logger = logging.getLogger(__name__)

API_BASE = "https://codeforces.com/api/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Difficulty buckets (problem ratings) for grouping solved problems
RATING_BUCKETS = {
    "easy": (0, 1200),
    "medium": (1201, 1600),
    "hard": (1601, 2000),
    "very_hard": (2001, 3000),
}

async def scrape(handle: str) -> ScrapeResponse:
    print(f"\n[Codeforces] Fetching data for: {handle}")

    # --- 1. User Info & Contest History ---
    user_info = await _fetch_user_info(handle)
    if user_info is None:
        return ScrapeResponse(platform="codeforces", handle=handle, error="Failed to fetch user info")

    rating = user_info.get("rating")
    max_rating = user_info.get("maxRating")
    rank = user_info.get("rank")

    contest_history = await _fetch_contest_history(handle)
    contest_given = len(contest_history) if contest_history else 0

    # --- 2. Submissions ---
    submissions_data = await _fetch_all_submissions(handle)
    if submissions_data is None:
        calendar_info = CalendarInfo(total_active_days=0, badges=[])
        return ScrapeResponse(
            platform="codeforces",
            handle=handle,
            total_solved=0,
            rating=rating,
            contest_given=contest_given,
            difficulty_counts={},
            max_streak_lifetime=0,
            max_streak_current_year=0,
            active_days=0,
            calendar_info=calendar_info,
            solved_questions_by_category={},
            heatmap_data=[]
        )

    # --- 3. Process submissions ---
    total_solved, difficulty_counts, solved_questions_by_category, date_counts, _ = _process_submissions(submissions_data)

    # --- 4. Compute streaks and heatmap ---
    one_year_ago = datetime.now() - timedelta(days=365)
    filtered_dates = {d: count for d, count in date_counts.items() if d >= one_year_ago.date()}
    active_days = len(filtered_dates)
    heatmap_data = []
    max_streak_lifetime = 0
    max_streak_current_year = 0
    current_year = datetime.now().year

    if filtered_dates:
        sorted_dates = sorted(filtered_dates.keys())
        heatmap_data = [HeatmapDay(date=d.isoformat(), count=filtered_dates[d]) for d in sorted_dates]

        # Lifetime streak on filtered dates
        current_streak = 0
        prev = None
        for d in sorted_dates:
            if prev is None:
                current_streak = 1
            elif (d - prev).days == 1:
                current_streak += 1
            else:
                current_streak = 1
            max_streak_lifetime = max(max_streak_lifetime, current_streak)
            prev = d

        # Current year streak
        current_streak = 0
        prev = None
        for d in sorted_dates:
            if d.year == current_year:
                if prev is None:
                    current_streak = 1
                elif (d - prev).days == 1:
                    current_streak += 1
                else:
                    current_streak = 1
                max_streak_current_year = max(max_streak_current_year, current_streak)
                prev = d
            else:
                current_streak = 0
                prev = None

    # --- 5. Build response ---
    calendar_info = CalendarInfo(
        total_active_days=active_days,
        badges=[]
    )

    return ScrapeResponse(
        platform="codeforces",
        handle=handle,
        total_solved=total_solved,
        rating=rating,
        contest_given=contest_given,
        difficulty_counts=difficulty_counts if difficulty_counts else {},
        max_streak_lifetime=max_streak_lifetime,
        max_streak_current_year=max_streak_current_year,
        active_days=active_days,
        calendar_info=calendar_info,
        solved_questions_by_category=solved_questions_by_category if solved_questions_by_category else {},
        heatmap_data=heatmap_data if heatmap_data else []
    )


async def _fetch_user_info(handle: str) -> Optional[Dict]:
    url = API_BASE + f"user.info?handles={handle}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code == 200:
                data = resp.json()
                if data["status"] == "OK" and data["result"]:
                    user = data["result"][0]
                    return {
                        "rating": user.get("rating"),
                        "maxRating": user.get("maxRating"),
                        "rank": user.get("rank")
                    }
            else:
                print(f"[Codeforces] user.info status {resp.status_code}")
    except Exception as e:
        print(f"[Codeforces] user.info error: {e}")
    return None


async def _fetch_contest_history(handle: str) -> List[Dict]:
    url = API_BASE + f"user.rating?handle={handle}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code == 200:
                data = resp.json()
                if data["status"] == "OK":
                    return data["result"]
            else:
                print(f"[Codeforces] user.rating status {resp.status_code}")
    except Exception as e:
        print(f"[Codeforces] user.rating error: {e}")
    return []


async def _fetch_all_submissions(handle: str) -> Optional[List[Dict]]:
    all_submissions = []
    from_index = 1
    count = 1000
    max_attempts = 100

    async with httpx.AsyncClient(timeout=15.0) as client:
        for attempt in range(max_attempts):
            url = API_BASE + f"user.status?handle={handle}&from={from_index}&count={count}"
            try:
                resp = await client.get(url, headers=HEADERS)
                if resp.status_code != 200:
                    print(f"[Codeforces] user.status status {resp.status_code}")
                    break
                data = resp.json()
                if data["status"] != "OK":
                    print(f"[Codeforces] user.status error: {data.get('comment')}")
                    break
                submissions = data["result"]
                if not submissions:
                    break
                all_submissions.extend(submissions)
                if len(submissions) < count:
                    break
                from_index += count
                await asyncio.sleep(0.2)
            except Exception as e:
                print(f"[Codeforces] user.status error: {e}")
                break

    print(f"[Codeforces] Total submissions fetched: {len(all_submissions)}")
    return all_submissions


def _process_submissions(submissions: List[Dict]) -> Tuple[int, Dict[str, int], Dict[str, List[str]], Dict, List]:
    accepted = [s for s in submissions if s.get("verdict") == "OK"]
    print(f"[Codeforces] Accepted submissions: {len(accepted)}")

    solved_problems = set()
    solved_by_category_counts = defaultdict(int)
    solved_by_category_names = defaultdict(list)
    date_counts = defaultdict(int)

    for sub in accepted:
        problem = sub.get("problem", {})
        problem_name = problem.get("name")
        if not problem_name:
            continue
        key = f"{problem.get('contestId')}_{problem.get('index')}_{problem_name}"
        if key in solved_problems:
            continue
        solved_problems.add(key)

        rating = problem.get("rating")
        category = "unknown"
        if rating is not None:
            for cat, (low, high) in RATING_BUCKETS.items():
                if low <= rating <= high:
                    category = cat
                    break
            else:
                category = "very_hard" if rating > 2000 else "medium"
        else:
            # If no rating, use a default (e.g., "unknown")
            category = "unknown"

        solved_by_category_counts[category] += 1
        solved_by_category_names[category].append(problem_name)

        ts = sub.get("creationTimeSeconds")
        if ts:
            dt = datetime.fromtimestamp(ts).date()
            date_counts[dt] += 1

    total_solved = len(solved_problems)
    return total_solved, dict(solved_by_category_counts), dict(solved_by_category_names), date_counts, list(solved_problems)