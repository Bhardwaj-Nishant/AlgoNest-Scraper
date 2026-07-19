import httpx
import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Any
from bs4 import BeautifulSoup
import re
import asyncio
from .base import ScrapeResponse, CalendarInfo, HeatmapDay

logger = logging.getLogger(__name__)

PROFILE_API_VERCEL = "https://codechef-api.vercel.app/api/user?username={handle}"
PROFILE_API_OFFICIAL = "https://www.codechef.com/api/user/profile?username={handle}"
STATUS_API = "https://www.codechef.com/api/status?handle={handle}&page={page}"
PROFILE_URL = "https://www.codechef.com/users/{handle}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.codechef.com/",
}


async def scrape(handle: str) -> ScrapeResponse:
    print(f"\n[CodeChef] Fetching data for: {handle}")

    # --- 1. Profile Stats ---
    profile_data = await _fetch_profile(handle)
    if profile_data is None:
        return ScrapeResponse(platform="codechef", handle=handle, error="Failed to fetch profile data")

    rating = profile_data.get("rating")
    total_solved = profile_data.get("solved", 0)
    contest_given = profile_data.get("contests", 0)
    stars = profile_data.get("stars")
    badges_list = profile_data.get("badges", [])

    print(f"[CodeChef] Profile: Rating={rating}, Solved={total_solved}, Contests={contest_given}")

    # --- 2. Heatmap & Solved Questions (from profile page) ---
    heatmap_data = await _fetch_heatmap_from_profile(handle)
    if heatmap_data is None:
        print("[CodeChef] Heatmap fetch failed, returning partial data")
        calendar_info = CalendarInfo(total_active_days=0, badges=_build_badges(stars, badges_list))
        return ScrapeResponse(
            platform="codechef",
            handle=handle,
            total_solved=total_solved,
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

    # Unpack the heatmap result
    solved_questions = heatmap_data.get("solved_questions", {})
    max_streak_lifetime = heatmap_data.get("max_streak_lifetime", 0)
    max_streak_current_year = heatmap_data.get("max_streak_current_year", 0)
    active_days = heatmap_data.get("active_days", 0)
    heatmap_list = heatmap_data.get("heatmap_data", [])

    calendar_info = CalendarInfo(total_active_days=active_days, badges=_build_badges(stars, badges_list))

    return ScrapeResponse(
        platform="codechef",
        handle=handle,
        total_solved=total_solved,
        rating=rating,
        contest_given=contest_given,
        difficulty_counts={},
        max_streak_lifetime=max_streak_lifetime,
        max_streak_current_year=max_streak_current_year,
        active_days=active_days,
        calendar_info=calendar_info,
        solved_questions_by_category=solved_questions if solved_questions else {},
        heatmap_data=heatmap_list if heatmap_list else []
    )


def _build_badges(stars: Optional[str], extra_badges: List[Dict]) -> List[Dict]:
    badges = []
    if stars:
        badges.append({"name": "Stars", "icon": stars})
    if extra_badges:
        badges.extend(extra_badges)
    return badges


async def _fetch_profile(handle: str) -> Optional[Dict]:
    # HTML first (accurate contest count)
    result = await _fetch_profile_html(handle)
    if result and result.get("contests") is not None:
        return result

    result = await _fetch_profile_vercel(handle)
    if result:
        return result

    result = await _fetch_profile_official(handle)
    if result:
        return result

    return None


async def _fetch_profile_vercel(handle: str) -> Optional[Dict]:
    url = PROFILE_API_VERCEL.format(handle=handle)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code == 200:
                data = resp.json()
                rating = data.get("rating")
                if rating is not None:
                    rating = int(rating)
                solved = data.get("totalSolved")
                if solved is not None:
                    solved = int(solved)
                contests = data.get("totalContests")
                if contests is not None:
                    contests = int(contests)
                stars = data.get("stars")
                print(f"[CodeChef] Vercel: Rating={rating}, Solved={solved}, Contests={contests}")
                return {
                    "rating": rating,
                    "solved": solved,
                    "contests": contests,
                    "stars": stars,
                    "badges": []
                }
            else:
                print(f"[CodeChef] Vercel status {resp.status_code}")
    except Exception as e:
        print(f"[CodeChef] Vercel error: {e}")
    return None


async def _fetch_profile_official(handle: str) -> Optional[Dict]:
    url = PROFILE_API_OFFICIAL.format(handle=handle)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code == 200:
                data = resp.json()
                user = data.get("data", {}) or data
                rating = user.get("rating") or user.get("currentRating")
                if rating is not None:
                    rating = int(rating)
                solved = user.get("solved") or user.get("problemsSolved")
                if solved is not None:
                    solved = int(solved)
                contests = user.get("contests") or user.get("participatedContests")
                if contests is not None:
                    contests = int(contests)
                if rating is not None or solved is not None:
                    print(f"[CodeChef] Official: Rating={rating}, Solved={solved}, Contests={contests}")
                    return {
                        "rating": rating,
                        "solved": solved,
                        "contests": contests,
                        "stars": None,
                        "badges": []
                    }
            else:
                print(f"[CodeChef] Official status {resp.status_code}")
    except Exception as e:
        print(f"[CodeChef] Official error: {e}")
    return None


async def _fetch_profile_html(handle: str) -> Optional[Dict]:
    url = PROFILE_URL.format(handle=handle)
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code != 200:
                print(f"[CodeChef] HTML fetch status {resp.status_code}")
                return None
            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            # Rating
            rating = None
            rating_elem = soup.select_one(".rating-number")
            if rating_elem:
                rating_text = rating_elem.text.strip()
                if rating_text.isdigit():
                    rating = int(rating_text)

            # Solved
            solved = None
            solved_match = re.search(r'(?:Problems|Total)\s+Solved[:\s]+(\d+)', html, re.IGNORECASE)
            if solved_match:
                solved = int(solved_match.group(1))

            # Contests
            contests = None
            patterns = [
                r'Contests?\s+(?:Participated|Attended)[:\s]+(\d+)',
                r'Total\s+Contests[:\s]+(\d+)',
                r'Contests\s+Count[:\s]+(\d+)',
            ]
            for pat in patterns:
                match = re.search(pat, html, re.IGNORECASE)
                if match:
                    contests = int(match.group(1))
                    break

            if contests is None:
                for elem in soup.find_all(['div', 'span'], class_=re.compile(r'contest', re.IGNORECASE)):
                    text = elem.text.strip()
                    numbers = re.findall(r'\d+', text)
                    if numbers:
                        contests = min(int(n) for n in numbers)
                        break

            # Stars
            stars = None
            star_elem = soup.select_one(".user-stars, .rating-star")
            if star_elem:
                star_text = star_elem.text.strip()
                if "★" in star_text or "⭐" in star_text:
                    stars = star_text

            # Badges
            badges = []
            badge_elems = soup.select(".badge, .user-badge")
            for badge in badge_elems:
                name = badge.text.strip()
                icon = badge.select_one("img")
                icon_url = icon.get("src") if icon else None
                badges.append({"name": name, "icon": icon_url})

            print(f"[CodeChef] HTML: Rating={rating}, Solved={solved}, Contests={contests}")
            if rating is not None or solved is not None:
                return {
                    "rating": rating,
                    "solved": solved or 0,
                    "contests": contests or 0,
                    "stars": stars,
                    "badges": badges
                }
            return None
    except Exception as e:
        print(f"[CodeChef] HTML error: {e}")
        return None


async def _fetch_heatmap_from_profile(handle: str) -> Optional[Dict]:
    """
    Parse the profile page's "Recent Activity" table to extract accepted submissions.
    This is the most reliable source for heatmap data.
    """
    url = PROFILE_URL.format(handle=handle)
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code != 200:
                print(f"[CodeChef] Heatmap fetch status {resp.status_code}")
                return None
            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            # Find the "Recent Activity" table – it's usually a table with class "dataTable"
            # or it's inside a div with id "rankContentDiv" (as seen in API responses).
            # We search for any table that contains rows with "tick-icon".
            rows = soup.select("tr:has(img[src*='tick-icon'])")
            if not rows:
                # Fallback: search the entire HTML for tick-icon img and then get parent row
                print("[CodeChef] No rows with tick-icon found via selector, trying regex fallback...")
                return await _extract_heatmap_from_regex(html)

            print(f"[CodeChef] Found {len(rows)} rows with tick-icon")

            date_counts = defaultdict(int)
            solved_problems = set()

            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 2:
                    continue
                # Problem name: usually in second column
                problem_col = cols[1]
                link = problem_col.find("a")
                problem_name = link.text.strip() if link else None
                if problem_name:
                    solved_problems.add(problem_name)

                # Date: in first column, in title attribute
                time_col = cols[0]
                date_text = time_col.get('title', '').strip()
                if not date_text:
                    date_text = time_col.get_text(strip=True)
                if date_text:
                    # Try to parse date (format: "08:53 PM 27/05/26")
                    try:
                        # Use regex to extract day/month/year
                        date_match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', date_text)
                        if date_match:
                            day, month, year = date_match.groups()
                            if len(year) == 2:
                                year = f"20{year}"
                            dt = datetime.strptime(f"{day}/{month}/{year}", "%d/%m/%Y").date()
                            date_counts[dt] += 1
                        else:
                            # Try full date-time parsing
                            dt = datetime.strptime(date_text, "%I:%M %p %d/%m/%y").date()
                            date_counts[dt] += 1
                    except Exception as e:
                        print(f"[CodeChef] Date parse error: {e} for '{date_text}'")

            if not date_counts:
                print("[CodeChef] No valid dates extracted from rows. Trying regex fallback...")
                return await _extract_heatmap_from_regex(html)

            print(f"[CodeChef] Extracted {len(date_counts)} unique dates, {len(solved_problems)} unique problems")
            return _process_heatmap_data(date_counts, list(solved_problems))

    except Exception as e:
        print(f"[CodeChef] Heatmap extraction error: {e}")
        return None


async def _extract_heatmap_from_regex(html: str) -> Optional[Dict]:
    """
    Fallback: use regex to find all accepted submissions in the HTML.
    This works even if BeautifulSoup fails to parse the table.
    """
    print("[CodeChef] Using regex fallback for heatmap...")
    # Find all table rows that contain a tick-icon image
    pattern = r'<tr>.*?<td title="([^"]+)".*?<img[^>]*tick-icon[^>]*>.*?<a[^>]*>([^<]+)</a>'
    matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)

    if not matches:
        print("[CodeChef] No accepted submissions found via regex.")
        return None

    date_counts = defaultdict(int)
    solved_problems = set()
    for date_text, problem_name in matches:
        if problem_name:
            solved_problems.add(problem_name.strip())
        if date_text:
            try:
                # Extract date (format: "08:53 PM 27/05/26")
                date_match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', date_text)
                if date_match:
                    day, month, year = date_match.groups()
                    if len(year) == 2:
                        year = f"20{year}"
                    dt = datetime.strptime(f"{day}/{month}/{year}", "%d/%m/%Y").date()
                    date_counts[dt] += 1
                else:
                    dt = datetime.strptime(date_text, "%I:%M %p %d/%m/%y").date()
                    date_counts[dt] += 1
            except Exception as e:
                print(f"[CodeChef] Regex date parse error: {e} for '{date_text}'")

    if not date_counts:
        return None

    print(f"[CodeChef] Regex extracted {len(date_counts)} dates, {len(solved_problems)} problems")
    return _process_heatmap_data(date_counts, list(solved_problems))


def _process_heatmap_data(date_counts: Dict, solved_problems: List[str]) -> Dict:
    """
    Compute streaks and heatmap from date_counts and solved problems.
    """
    # Filter last 365 days
    one_year_ago = datetime.now() - timedelta(days=365)
    filtered_dates = {d: count for d, count in date_counts.items() if d >= one_year_ago.date()}

    solved_questions = {"all": solved_problems} if solved_problems else {}

    max_streak_lifetime = 0
    max_streak_current_year = 0
    active_days = len(filtered_dates)
    current_year = datetime.now().year
    heatmap_data = []

    if filtered_dates:
        sorted_dates = sorted(filtered_dates.keys())
        heatmap_data = [HeatmapDay(date=d.isoformat(), count=filtered_dates[d]) for d in sorted_dates]

        # Lifetime streak (on filtered dates)
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

    return {
        "solved_questions": solved_questions,
        "max_streak_lifetime": max_streak_lifetime,
        "max_streak_current_year": max_streak_current_year,
        "active_days": active_days,
        "heatmap_data": heatmap_data
    }