"""Discover new NEMCC box scores by scraping schedule pages.

Fetches each sport's schedule page and extracts box score URLs
that haven't been processed yet.
"""

from __future__ import annotations

import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from rss_to_wp.boxscores.config import NEMCC_BASE_URL, SportConfig
from rss_to_wp.utils import get_logger

logger = get_logger("boxscores.discovery")

# Regex pattern to match box score URLs in schedule pages
BOXSCORE_URL_PATTERN = re.compile(
    r"/sports/[a-z]+/\d{4}-\d{2}/boxscores/(\d{8})_(\w+)\.xml"
)

# Standard browser headers to avoid blocks
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def discover_boxscores(sport: SportConfig) -> list[dict]:
    """Scrape a sport's schedule page and return all box score URLs.

    Args:
        sport: Sport configuration with schedule URL.

    Returns:
        List of dicts with keys: url, game_date, game_id, sport_code, sport_name
    """
    schedule_url = sport.schedule_url
    logger.info("discovering_boxscores", sport=sport.name, url=schedule_url)

    try:
        response = requests.get(
            schedule_url,
            headers=BROWSER_HEADERS,
            timeout=(10, 30),
        )
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error("schedule_fetch_error", sport=sport.name, error=str(e))
        return []

    soup = BeautifulSoup(response.content, "html.parser")

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
