from fastapi import FastAPI, HTTPException, Query
from scrapers import leetcode, codeforces, github, gfg, codechef
from scrapers.base import ScrapeResponse
from dotenv import load_dotenv
import logging

load_dotenv()  # Load environment variables

app = FastAPI(title="AlgoNest Scraper", version="1.0")

# Map platform strings to their scraper functions
SCRAPER_MAP = {
    "leetcode": leetcode.scrape,
    "codeforces": codeforces.scrape,
    "github": github.scrape,
    "gfg": gfg.scrape,
    "codechef": codechef.scrape,
}

@app.get("/health")
async def health():
    return {"status": "healthy"}

# 👇 CHANGED: Now accepts BOTH GET and POST for easy testing!
@app.api_route("/scrape", methods=["GET", "POST"])
async def scrape_platform(
    platform: str = Query(..., description="Platform to scrape (e.g., leetcode, github)"),
    handle: str = Query(..., description="Username/handle on the platform")
):
    """
    Scrape a coding platform.
    Supports: leetcode, codeforces, github, gfg, codechef
    """
    platform = platform.lower()
    scraper_func = SCRAPER_MAP.get(platform)
    
    if not scraper_func:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform}")
    
    return await scraper_func(handle)

# For running directly
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

