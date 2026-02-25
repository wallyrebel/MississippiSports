"""Discover new NEMCC box scores by scraping schedule pages.

Uses Playwright in headed mode with xvfb on GitHub Actions to bypass
Cloudflare's headless browser detection. Falls back to a local JSON
cache if Playwright discovery fails.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

from rss_to_wp.boxscores.config import NEMCC_BASE_URL, SportConfig
from rss_to_wp.utils import get_logger

logger = get_logger("boxscores.discovery")

# Regex pattern to match box score URLs in schedule pages
BOXSCORE_URL_PATTERN = re.compile(
    r"/sports/[a-z]+/\d{4}-\d{2}/boxscores/(\d{8})_(\w+)\.xml"
)

# Path to the cached box score URLs
CACHE_FILE = Path("data/boxscore_cache.json")


def _fetch_page(url: str) -> Optional[str]:
    """Fetch a page using Playwright in HEADED mode (not headless).

    When run under xvfb on GitHub Actions, headed mode makes the browser
    indistinguishable from a real desktop browser. Cloudflare cannot detect
    this as headless/automated.

    Falls back to cloudscraper for local development on Windows.

    Args:
        url: URL to fetch.

    Returns:
        Page HTML as string, or None on failure.
    """
    # Try Playwright first
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # HEADED mode — with xvfb this looks like a real browser
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
            )

            # Remove webdriver flag
            page = context.new_page()
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)

                # Wait for schedule content to appear
                try:
                    page.wait_for_selector(
                        "a[href*='boxscore'], .sidearm-schedule-games, "
                        "table, .sidearm-schedule-game",
                        timeout=15000,
                    )
                except Exception:
                    pass

                # Extra wait for full JS rendering
                page.wait_for_timeout(5000)
                content = page.content()

                # Check if we got real content
                has_boxscores = "boxscore" in content.lower()
                logger.info(
                    "playwright_fetch_success",
                    url=url,
                    size=len(content),
                    has_boxscore_links=has_boxscores,
                )

                # If page is too small, it's probably still a challenge page
                if len(content) < 5000:
                    logger.warning("playwright_got_challenge_page", url=url, size=len(content))
                    return None

                return content

            except Exception as e:
                logger.warning("playwright_page_error", url=url, error=str(e))
                return None
            finally:
                context.close()
                browser.close()

    except ImportError:
        logger.info("playwright_not_installed_using_fallback")
    except Exception as e:
        # Playwright headed mode fails without display (e.g. no xvfb)
        logger.info("playwright_headed_failed", error=str(e))

    # Fallback: try cloudscraper (works locally)
    try:
        import cloudscraper

        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )
        response = scraper.get(url, timeout=30)
        response.raise_for_status()
        content = response.text

        if len(content) > 10000:
            logger.info("cloudscraper_fetch_success", url=url, size=len(content))
            return content
    except Exception as e:
        logger.warning("cloudscraper_fetch_error", url=url, error=str(e))

    return None


def _scrape_schedule_page(html: str, sport: SportConfig) -> list[dict]:
    """Parse box score URLs from schedule page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    boxscore_urls: dict[str, dict] = {}

    for link in soup.find_all("a", href=True):
        href = link["href"]

        match = BOXSCORE_URL_PATTERN.search(href)
        if not match:
            continue

        game_date = match.group(1)
        game_id = match.group(2)

        if href.startswith("/"):
            full_url = f"{NEMCC_BASE_URL}{href}"
        elif href.startswith("http"):
            full_url = href
        else:
            continue

        if full_url not in boxscore_urls:
            boxscore_urls[full_url] = {
                "url": full_url,
                "game_date": game_date,
                "game_id": game_id,
                "sport_code": sport.code,
                "sport_name": sport.name,
                "sport_type": sport.sport_type,
            }

    return list(boxscore_urls.values())


def _load_cache() -> list[dict]:
    """Load cached box score URLs from JSON file."""
    if not CACHE_FILE.exists():
        return []
    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
        logger.info("cache_loaded", count=len(data))
        return data
    except Exception as e:
        logger.warning("cache_load_error", error=str(e))
        return []


def _save_cache(boxscores: list[dict]) -> None:
    """Save discovered box score URLs to JSON cache."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    existing = _load_cache()
    existing_urls = {bs["url"] for bs in existing}
    new_entries = [bs for bs in boxscores if bs["url"] not in existing_urls]
    merged = existing + new_entries

    with open(CACHE_FILE, "w") as f:
        json.dump(merged, f, indent=2)

    logger.info("cache_saved", total=len(merged), new=len(new_entries))


def discover_boxscores(sport: SportConfig) -> list[dict]:
    """Discover box scores for a sport by scraping its schedule page."""
    schedule_url = sport.schedule_url
    logger.info("discovering_boxscores", sport=sport.name, url=schedule_url)

    html = _fetch_page(schedule_url)
    if html is None:
        return []

    results = _scrape_schedule_page(html, sport)
    logger.info("boxscores_discovered", sport=sport.name, count=len(results))
    return results


def discover_all_boxscores(
    sports: Optional[list[SportConfig]] = None,
) -> list[dict]:
    """Discover box scores across all sports.

    Strategy:
    1. Try live discovery via Playwright/cloudscraper
    2. If it finds results, save them to cache
    3. If live fails (GH Actions without xvfb), fall back to cache
    """
    from rss_to_wp.boxscores.config import NEMCC_SPORTS

    if sports is None:
        sports = [s for s in NEMCC_SPORTS if s.enabled]

    all_boxscores: list[dict] = []

    for i, sport in enumerate(sports):
        try:
            if i > 0:
                time.sleep(2)
            boxscores = discover_boxscores(sport)
            all_boxscores.extend(boxscores)
        except Exception as e:
            logger.error("sport_discovery_error", sport=sport.name, error=str(e))
            continue

    if all_boxscores:
        logger.info("live_discovery_succeeded", total=len(all_boxscores))
        _save_cache(all_boxscores)
    else:
        logger.info("live_discovery_failed_using_cache")
        all_boxscores = _load_cache()

    logger.info(
        "total_boxscores_discovered",
        total=len(all_boxscores),
        sports_scanned=len(sports),
    )

    return all_boxscores


def update_cache(sports: Optional[list[SportConfig]] = None) -> int:
    """Run local discovery and update the cache. Returns total cached count."""
    from rss_to_wp.boxscores.config import NEMCC_SPORTS

    if sports is None:
        sports = [s for s in NEMCC_SPORTS if s.enabled]

    all_boxscores: list[dict] = []
    for i, sport in enumerate(sports):
        if i > 0:
            time.sleep(2)
        try:
            boxscores = discover_boxscores(sport)
            all_boxscores.extend(boxscores)
        except Exception as e:
            logger.error("cache_update_error", sport=sport.name, error=str(e))

    if all_boxscores:
        _save_cache(all_boxscores)

    cache = _load_cache()
    return len(cache)
