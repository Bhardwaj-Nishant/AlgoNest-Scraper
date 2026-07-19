import asyncio
from datetime import datetime
import requests
import json
import logging
from typing import Optional, Dict, List, Any
from .base import (
    ScrapeResponse, SkillCategory, ContestRankingInfo,
    ContestHistoryEntry, BeatsPercentage, CalendarInfo, HeatmapDay
)

logger = logging.getLogger(__name__)

LEETCODE_GRAPHQL_URL = "https://leetcode.com/graphql"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Referer": "https://leetcode.com/",
    "Origin": "https://leetcode.com",
}

async def scrape(handle: str) -> ScrapeResponse:
    """
    Fetches ALL LeetCode data for a user using 5 concurrent GraphQL queries.
    """
    logger.info(f"Fetching full LeetCode data for: {handle}")

    queries = {
        "skillStats": {
            "query": """
            query skillStats($username: String!) {
              matchedUser(username: $username) {
                tagProblemCounts {
                  advanced { tagName tagSlug problemsSolved }
                  intermediate { tagName tagSlug problemsSolved }
                  fundamental { tagName tagSlug problemsSolved }
                }
              }
            }
            """,
            "variables": {"username": handle}
        },
        "contestInfo": {
            "query": """
            query userContestRankingInfo($username: String!) {
              userContestRanking(username: $username) {
                attendedContestsCount
                rating
                globalRanking
                totalParticipants
                topPercentage
                badge { name }
              }
              userContestRankingHistory(username: $username) {
                attended
                trendDirection
                problemsSolved
                totalProblems
                finishTimeInSeconds
                rating
                ranking
                contest { title startTime }
              }
            }
            """,
            "variables": {"username": handle}
        },
        "progressV2": {
            "query": """
            query userProfileUserQuestionProgressV2($userSlug: String!) {
              userProfileUserQuestionProgressV2(userSlug: $userSlug) {
                numAcceptedQuestions { count difficulty }
                numFailedQuestions { count difficulty }
                numUntouchedQuestions { count difficulty }
                userSessionBeatsPercentage { difficulty percentage }
                totalQuestionBeatsPercentage
              }
            }
            """,
            "variables": {"userSlug": handle}
        },
        "sessionProgress": {
            "query": """
            query userSessionProgress($username: String!) {
              allQuestionsCount { difficulty count }
              matchedUser(username: $username) {
                submitStats {
                  acSubmissionNum { difficulty count submissions }
                  totalSubmissionNum { difficulty count submissions }
                }
              }
            }
            """,
            "variables": {"username": handle}
        },
        "calendar": {
            "query": """
            query userProfileCalendar($username: String!, $year: Int) {
              matchedUser(username: $username) {
                userCalendar(year: $year) {
                  activeYears
                  streak
                  totalActiveDays
                  dccBadges { timestamp badge { name icon } }
                  submissionCalendar
                }
              }
            }
            """,
            "variables": {"username": handle, "year": 2026}
        }
    }

    try:
        loop = asyncio.get_event_loop()
        
        def make_requests():
            session = requests.Session()
            results = {}
            for name, payload in queries.items():
                try:
                    resp = session.post(
                        LEETCODE_GRAPHQL_URL,
                        json=payload,
                        headers=HEADERS,
                        timeout=15
                    )
                    results[name] = resp.json()
                except Exception as e:
                    logger.error(f"Query '{name}' failed: {e}")
                    results[name] = {"error": str(e)}
            return results

        all_responses = await loop.run_in_executor(None, make_requests)
        return await _parse_all_data(handle, all_responses)

    except Exception as e:
        logger.error(f"Critical error in LeetCode scraper: {e}")
        return ScrapeResponse(platform="leetcode", handle=handle, error=str(e))


async def _parse_all_data(handle: str, all_responses: Dict[str, Any]) -> ScrapeResponse:
    response = ScrapeResponse(platform="leetcode", handle=handle)

    # --- 1. Session Progress ---
    session_data = all_responses.get("sessionProgress", {}).get("data", {})
    if "errors" not in all_responses.get("sessionProgress", {}):
        matched_user = session_data.get("matchedUser", {})
        submit_stats = matched_user.get("submitStats", {})
        ac_list = submit_stats.get("acSubmissionNum", [])
        total_list = submit_stats.get("totalSubmissionNum", [])
        
        difficulty_counts = {}
        total_solved = 0
        total_submissions = 0
        total_accepted = 0
        
        for item in ac_list:
            diff = item.get("difficulty", "").lower()
            count = item.get("count", 0)
            if diff == "all":
                total_solved = count
                total_accepted = count
            else:
                difficulty_counts[diff] = count
        
        for item in total_list:
            if item.get("difficulty", "").lower() == "all":
                total_submissions = item.get("count", 0)
                break
        
        response.total_solved = total_solved
        response.difficulty_counts = difficulty_counts if difficulty_counts else None

    # --- 2. Calendar and Heatmap ---
    calendar_current_data = all_responses.get("calendar", {}).get("data", {})
    if "errors" not in all_responses.get("calendar", {}):
        user_calendar_current = calendar_current_data.get("matchedUser", {}).get("userCalendar", {})
        active_years = user_calendar_current.get("activeYears", [])
        current_year = datetime.now().year
        loop = asyncio.get_event_loop()
        
        def fetch_calendar_for_year(year):
            query = """
            query userProfileCalendar($username: String!, $year: Int) {
              matchedUser(username: $username) {
                userCalendar(year: $year) {
                  submissionCalendar
                }
              }
            }
            """
            variables = {"username": handle, "year": year}
            return requests.post(
                "https://leetcode.com/graphql",
                json={"query": query, "variables": variables},
                headers=HEADERS,
                timeout=10
            ).json()
        
        if not active_years:
            active_years = [current_year]
        
        tasks = [loop.run_in_executor(None, fetch_calendar_for_year, year) for year in active_years]
        calendar_responses = await asyncio.gather(*tasks)
        
        merged_calendar = {}
        current_year_calendar = {}
        
        for year, resp in zip(active_years, calendar_responses):
            cal = resp.get("data", {}).get("matchedUser", {}).get("userCalendar", {})
            cal_str = cal.get("submissionCalendar")
            if cal_str:
                try:
                    cal_data = json.loads(cal_str)
                    merged_calendar.update(cal_data)
                    if year == current_year:
                        current_year_calendar = cal_data
                except Exception as e:
                    logger.error(f"Failed to parse calendar for year {year}: {e}")
        
        # --- Build heatmap_data ---
        heatmap_data = []
        for ts_str in sorted(merged_calendar.keys()):
            ts = int(ts_str)
            count = merged_calendar[ts_str]
            heatmap_data.append(HeatmapDay(
                date=datetime.fromtimestamp(ts).date().isoformat(),
                count=count
            ))
        
        # --- Calculate streaks ---
        lifetime_max_streak = 0
        current_streak = 0
        prev_ts = None
        for ts_str in sorted(merged_calendar.keys()):
            ts = int(ts_str)
            count = merged_calendar[ts_str]
            if count > 0:
                if prev_ts is None:
                    current_streak = 1
                elif ts - prev_ts == 86400:
                    current_streak += 1
                else:
                    current_streak = 1
                lifetime_max_streak = max(lifetime_max_streak, current_streak)
            else:
                current_streak = 0
            prev_ts = ts
        
        current_year_max_streak = 0
        current_streak = 0
        prev_ts = None
        for ts_str in sorted(current_year_calendar.keys()):
            ts = int(ts_str)
            count = current_year_calendar[ts_str]
            if count > 0:
                if prev_ts is None:
                    current_streak = 1
                elif ts - prev_ts == 86400:
                    current_streak += 1
                else:
                    current_streak = 1
                current_year_max_streak = max(current_year_max_streak, current_streak)
            else:
                current_streak = 0
            prev_ts = ts
        
        active_days = sum(1 for c in merged_calendar.values() if c > 0)
        
        response.max_streak_lifetime = lifetime_max_streak
        response.max_streak_current_year = current_year_max_streak
        response.active_days = active_days
        response.heatmap_data = heatmap_data
        
        # Badges
        dcc_badges = user_calendar_current.get("dccBadges", [])
        badges = []
        for b in dcc_badges:
            badge_info = b.get("badge", {})
            badges.append({
                "timestamp": b.get("timestamp"),
                "name": badge_info.get("name"),
                "icon": badge_info.get("icon")
            })
        response.calendar_info = CalendarInfo(
            total_active_days=active_days,
            badges=badges
        )

    # --- 3. Skill Stats ---
    skill_data = all_responses.get("skillStats", {}).get("data", {})
    if "errors" not in all_responses.get("skillStats", {}):
        tag_counts = skill_data.get("matchedUser", {}).get("tagProblemCounts", {})
        skill_breakdown = {}
        for level in ["advanced", "intermediate", "fundamental"]:
            items = tag_counts.get(level, [])
            if items: 
                skill_breakdown[level] = [
                    SkillCategory(
                        tag_name=item.get("tagName"),
                        tag_slug=item.get("tagSlug"),
                        problems_solved=item.get("problemsSolved", 0)
                    ) for item in items
                ]
        response.skill_breakdown = skill_breakdown if skill_breakdown else None

    # --- 4. Contest Data ---
    contest_data = all_responses.get("contestInfo", {}).get("data", {})
    if "errors" not in all_responses.get("contestInfo", {}):
        ranking = contest_data.get("userContestRanking")
        
        print("Ranking object:", ranking)

        if ranking:
            print("Contest Rating:", ranking.get("rating"))
            print("Global Rank:", ranking.get("globalRanking"))
            print("Participants:", ranking.get("totalParticipants"))

        if ranking:
            badge = ranking.get("badge", {})
            response.contest_ranking = ContestRankingInfo(
                attended_contests_count=ranking.get("attendedContestsCount", 0),
                rating=ranking.get("rating"),
                global_ranking=ranking.get("globalRanking"),
                total_participants=ranking.get("totalParticipants"),
                top_percentage=ranking.get("topPercentage"),
                badge_name=badge.get("name")
            )
            # Set the top-level rating to the contest rating
            if ranking.get("rating") is not None:
                response.rating = ranking.get("rating")
            else:
                response.rating = None
        else:
            # No contest ranking data
            response.rating = None
        
        history = contest_data.get("userContestRankingHistory", [])
        if history:
            history_list = []
            for entry in history:
                contest = entry.get("contest", {})
                history_list.append(
                    ContestHistoryEntry(
                        attended=entry.get("attended", False),
                        rating=entry.get("rating"),
                        ranking=entry.get("ranking"),
                        trend_direction=entry.get("trendDirection"),
                        problems_solved=entry.get("problemsSolved"),
                        total_problems=entry.get("totalProblems"),
                        finish_time=entry.get("finishTimeInSeconds"),
                        contest_title=contest.get("title"),
                        start_time=contest.get("startTime")
                    )
                )
            response.contest_history = history_list if history_list else None
    else:
        # If contest query fails, set rating to None
        response.rating = None

    # --- 5. Progress V2 ---
    progress_data = all_responses.get("progressV2", {}).get("data", {})
    if "errors" not in all_responses.get("progressV2", {}):
        progress_v2 = progress_data.get("userProfileUserQuestionProgressV2", {})
        
        accepted = progress_v2.get("numAcceptedQuestions", [])
        failed = progress_v2.get("numFailedQuestions", [])
        untouched = progress_v2.get("numUntouchedQuestions", [])
        
        progress_counts = {}
        for item in accepted:
            diff = item.get("difficulty", "").lower()
            progress_counts[f"accepted_{diff}"] = item.get("count", 0)
        for item in failed:
            diff = item.get("difficulty", "").lower()
            progress_counts[f"failed_{diff}"] = item.get("count", 0)
        for item in untouched:
            diff = item.get("difficulty", "").lower()
            progress_counts[f"untouched_{diff}"] = item.get("count", 0)
        
        progress_counts["accepted_total"] = sum(item.get("count", 0) for item in accepted if item.get("difficulty") == "All")
        progress_counts["failed_total"] = sum(item.get("count", 0) for item in failed if item.get("difficulty") == "All")
        progress_counts["untouched_total"] = sum(item.get("count", 0) for item in untouched if item.get("difficulty") == "All")
        
        response.question_progress = progress_counts if progress_counts else None

        beats = progress_v2.get("userSessionBeatsPercentage", [])
        if beats:
            beats_list = []
            for b in beats:
                beats_list.append(
                    BeatsPercentage(
                        difficulty=b.get("difficulty", "").lower(),
                        percentage=b.get("percentage", 0.0)
                    )
                )
            response.beats_percentage = beats_list if beats_list else None
        
        response.total_question_beats_percentage = progress_v2.get("totalQuestionBeatsPercentage")

    return response