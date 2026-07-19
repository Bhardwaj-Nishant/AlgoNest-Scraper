from pydantic import BaseModel
from typing import Optional, Dict, List, Any

# --- Shared / Common Models ---

class HeatmapDay(BaseModel):
    date: str
    count: int

class ContestHistoryEntry(BaseModel):
    attended: bool
    rating: Optional[float] = None
    ranking: Optional[int] = None
    trend_direction: Optional[str] = None
    problems_solved: Optional[int] = None
    total_problems: Optional[int] = None
    finish_time: Optional[int] = None
    contest_title: Optional[str] = None
    start_time: Optional[int] = None

class ContestRankingInfo(BaseModel):
    attended_contests_count: int = 0
    rating: Optional[float] = None
    global_ranking: Optional[int] = None
    total_participants: Optional[int] = None
    top_percentage: Optional[float] = None
    badge_name: Optional[str] = None

class BeatsPercentage(BaseModel):
    difficulty: str
    percentage: float

class SkillCategory(BaseModel):
    tag_name: str
    tag_slug: str
    problems_solved: int

# --- Updated Calendar Info (Removed active_years and streak) ---
class CalendarInfo(BaseModel):
    total_active_days: int = 0
    badges: List[Dict[str, Any]] = []  # {timestamp, name, icon}

# --- The ONE Universal Response Model ---
class ScrapeResponse(BaseModel):
    platform: str
    handle: str
    
    # ========== CORE STATS ==========
    total_solved: Optional[int] = None
    rating: Optional[int] = None
    contest_given: Optional[int] = None
    difficulty_counts: Optional[Dict[str, int]] = None  # {"easy": 20, "medium": 15}
    
    # ========== LEETCODE SPECIFIC ==========
    skill_breakdown: Optional[Dict[str, List[SkillCategory]]] = None
    contest_ranking: Optional[ContestRankingInfo] = None
    contest_history: Optional[List[ContestHistoryEntry]] = None
    question_progress: Optional[Dict[str, int]] = None
    beats_percentage: Optional[List[BeatsPercentage]] = None
    total_question_beats_percentage: Optional[float] = None
    
    # Activity Stats (Direct top-level fields)
    total_submissions_last_year: Optional[int] = None
    max_streak_lifetime: Optional[int] = None       # Combined across ALL years
    max_streak_current_year: Optional[int] = None   # Specific to current year (e.g., 2026)
    active_days: Optional[int] = None               # Total active days across ALL years
    calendar_info: Optional[CalendarInfo] = None    # Badges (from the current year)
    
    # ========== GITHUB SPECIFIC ==========
    total_repos: Optional[int] = None
    total_contributions: Optional[int] = None
    heatmap_data: Optional[List[HeatmapDay]] = None

    # In scrapers/base.py, inside ScrapeResponse class:
    solved_questions_by_category: Optional[Dict[str, List[str]]] = None  # {"easy": ["Two Sum", ...], "medium": [...], ...}
    
    # ========== ERROR ==========
    error: Optional[str] = None