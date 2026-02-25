"""Discover new NEMCC box scores by scraping schedule pages.

Fetches each sport's schedule page and extracts box score URLs
that haven't been processed yet.
"""

from __future__ import annotations

import re
import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

from rss_to_wp.boxscores.config import NEMCC_BASE_URL, SportConfig
from rss_to_wp.utils import get_logger

logger = get_logger("boxscores.discovery")

# Regex pattern to match box score URLs in schedule pages
BOXSCORE_URL_PATTERN = re.compile(
    r"/sports/[a-z]+/\d{4}-\d{2}/boxscores/(\d{8})_(\w+)\.xml"
)


def _get_session() -> requests.Session:
    """Create a requests session that mimics a real browser.

    Includes retry logic, cookie persistence, and full browser headers
    to avoid 405/403 blocks from Sidearm/PrestoSports WAF.
    """
    session = requests.Session()

    # Retry strategy
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[403, 405, 429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    # Full browser-like headers
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "Referer": "https://www.nemccathletics.com/",
    })

    return session


# Shared session for all discovery requests in a run
_session: Optional[requests.Session] = None


def _fetch_page(url: str) -> Optional[bytes]:
    """Fetch a page with full browser mimicry and retry logic.

    First hits the main NEMCC page to get cookies, then fetches the target URL.
    """
    global _session

    if _session is None:
        _session = _get_session()
        # Warm up cookies by visiting the homepage first
        try:
            _session.get(
                NEMCC_BASE_URL,
                timeout=(10, 15),
                allow_redirects=True,
            )
            time.sleep(0.5)
        except requests.RequestException:
            pass  # Not critical — continue anyway

    try:
        response = _session.get(
            url,
            timeout=(10, 30),
            allow_redirects=True,
        )
        response.raise_for_status()
        return response.content
    except requests.RequestException as e:
        logger.error("page_fetch_error", url=url, error=str(e))
        return None


def discover_boxscores(sport: SportConfig) -> list[dict]:
    """Scrape a sport's schedule page and return all box score URLs.

    Args:
        sport: Sport configuration with schedule URL.

    Returns:
        List of dicts with keys: url, game_date, game_id, sport_code, sport_name
    """
    schedule_url = sport.schedule_url
    logger.info("discovering_boxscores", sport=sport.name, url=schedule_url)

    content = _fetch_page(schedule_url)
    if content is None:
        logger.error("schedule_fetch_error", sport=sport.name)
        return []

    soup = BeautifulSoup(content, "html.parser")

    # Find all links that match the box score URL pattern
    boxscore_urls: dict[str, dict] = {}  # Use dict to deduplicate by URL

    for link in soup.find_all("a", href=True):
        href = link["href"]

        # Match box score URLs
        match = BOXSCORE_URL_PATTERN.search(href)
        if not match:
            continue

        game_date = match.group(1)  # YYYYMMDD
        game_id = match.group(2)    # unique 4-char ID

        # Build full URL if relative
        if href.startswith("/"):
            full_url = f"{NEMCC_BASE_URL}{href}"
        elif href.startswith("http"):
            full_url = href
        else:
            continue

        # Deduplicate by URL
        if full_url not in boxscore_urls:
            boxscore_urls[full_url] = {
                "url": full_url,
                "game_date": game_date,
                "game_id": game_id,
                "sport_code": sport.code,
                "sport_name": sport.name,
                "sport_type": sport.sport_type,
            }

    results = list(boxscore_urls.values())

    logger.info(
        "boxscores_discovered",
        sport=sport.name,
        count=len(results),
    )

    return results


def discover_all_boxscores(
    sports: Optional[list[SportConfig]] = None,
) -> list[dict]:
    """Discover box scores across all configured NEMCC sports.

    Args:
        sports: List of sport configs to scan. Defaults to all enabled sports.

    Returns:
        Combined list of box score info dicts from all sports.
    """
    from rss_to_wp.boxscores.config import NEMCC_SPORTS

    if sports is None:
        sports = [s for s in NEMCC_SPORTS if s.enabled]

    all_boxscores: list[dict] = []

    for sport in sports:
        try:
            boxscores = discover_boxscores(sport)
            all_boxscores.extend(boxscores)
        except Exception as e:
            logger.error(
                "sport_discovery_error",
                sport=sport.name,
                error=str(e),
            )
            continue

    logger.info(
        "total_boxscores_discovered",
        total=len(all_boxscores),
        sports_scanned=len(sports),
    )

    return all_boxscores
