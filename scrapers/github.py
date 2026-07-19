import httpx
import os
from .base import ScrapeResponse
from datetime import datetime, timedelta

async def scrape(handle: str) -> ScrapeResponse:
    try:
        # Prepare GraphQL query for contributions
        # We'll get the contribution calendar for the last year
        query = """
        {
        user(login: "%s") {
            followers {
            totalCount
            }
            repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC) {
            totalCount
            nodes {
                name
            }
            }
            contributionsCollection {
            contributionCalendar {
                totalContributions
                weeks {
                contributionDays {
                    date
                    contributionCount
                }
                }
            }
            }
        }
        }
        """ % handle

        headers = {"Authorization": f"token {os.getenv('GITHUB_TOKEN', '')}"} if os.getenv('GITHUB_TOKEN') else {}
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.github.com/graphql",
                json={"query": query},
                headers=headers,
                timeout=15.0
            )
            
            if resp.status_code != 200:
                # Fallback: try REST API for basic info if GraphQL fails
                return await _fallback_rest(handle)
            
            data = resp.json()
            user_data = data.get("data", {}).get("user")
            if not user_data:
                return ScrapeResponse(platform="github", handle=handle, error="User not found")
            
            # Total repos
            repos = user_data.get("repositories", {}).get("totalCount", 0)

            repo_names = [
                repo["name"]
                for repo in user_data.get("repositories", {}).get("nodes", [])
            ]
            
            # Total followers
            followers = user_data.get("followers", {}).get("totalCount", 0)
            
            # Contributions calendar
            calendar = user_data.get("contributionsCollection", {}).get("contributionCalendar", {})
            total_contributions = calendar.get("totalContributions", 0)
            
            # Extract weekly contribution data for heatmap
            heatmap_data = []
            weeks = calendar.get("weeks", [])
            for week in weeks:
                for day in week.get("contributionDays", []):
                    heatmap_data.append({
                        "date": day.get("date"),  # String like "2025-07-13"
                        "count": day.get("contributionCount", 0)  # Integer
                    })
            
            return ScrapeResponse(
                platform="github",
                handle=handle,
                total_repos=repos,
                total_contributions=total_contributions,
                heatmap_data=heatmap_data,
                total_solved=repos,
                rating=followers,
                contest_given=None,
                difficulty_counts=None,
                solved_questions_by_category={
                    "Repositories": repo_names
                },
                accuracy=None
            )
            
    except Exception as e:
        return ScrapeResponse(platform="github", handle=handle, error=str(e))


async def _fallback_rest(handle: str) -> ScrapeResponse:
    """Fallback to REST API if GraphQL fails (e.g., no token or rate limit)"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.github.com/users/{handle}",
                timeout=15.0,
                headers={"Accept": "application/vnd.github.v3+json"}
            )
            if resp.status_code == 200:
                user = resp.json()
                return ScrapeResponse(
                    platform="github",
                    handle=handle,
                    total_repos=user.get("public_repos", 0),
                    total_contributions=None,  # Cannot get from REST
                    total_solved=user.get("public_repos", 0),
                    rating=user.get("followers", 0)
                )
            else:
                return ScrapeResponse(platform="github", handle=handle, error="User not found")
    except Exception as e:
        return ScrapeResponse(platform="github", handle=handle, error=str(e))