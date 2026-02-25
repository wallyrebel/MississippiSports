"""Discover new NEMCC box scores by scraping schedule pages.

Uses Playwright headless browser to bypass Cloudflare's JavaScript
challenge that blocks curl/requests/cloudscraper from GitHub Actions.
"""

from __future__ import annotations

import re
import time
from typing import Optional

from bs4 import BeautifulSoup

from rss_to_wp.boxscores.config import NEMCC_BASE_URL, SportConfig
from rss_to_wp.utils import get_logger

logger = get_logger("boxscores.discovery")

# Regex pattern to match box score URLs in schedule pages
BOXSCORE_URL_PATTERN = re.compile(
    r"/sports/[a-z]+/\d{4}-\d{2}/boxscores/(\d{8})_(\w+)\.xml"
)


def _fetch_page(url: str) -> Optional[str]:
    """Fetch a page using Playwright headless browser.

    Playwright runs a real Chromium browser that passes Cloudflare's
    JavaScript challenge and TLS fingerprinting. This is necessary
    because the NEMCC athletics site (Sidearm/PrestoSports) blocks
    all Python HTTP libraries from GitHub Actions runners.

    Falls back to cloudscraper for environments where Playwright
    browsers aren't installed (local dev).

    Args:
        url: URL to fetch.

    Returns:
        Page HTML as string, or None on failure.
    """
    # Try Playwright first (works on GitHub Actions with chromium installed)
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
            )
            page = context.new_page()

            try:
                # Navigate with longer timeout for Cloudflare challenge
                page.goto(url, wait_until="domcontentloaded", timeout=60000)

                # Wait for the actual schedule content to load
                # Sidearm pages use specific selectors for schedule data
                try:
                    page.wait_for_selector(
                        "a[href*='boxscore'], .sidearm-schedule-games, "
                        ".schedule-table, table, .sidearm-schedule-game",
                        timeout=15000,
                    )
                except Exception:
                    pass  # Might not have box scores; continue anyway

                # Extra wait for JS rendering after elements appear
                page.wait_for_timeout(5000)

                content = page.content()

                # Log first part of HTML for debugging
                preview = content[:300].replace("\n", " ").replace("\r", " ")
                logger.info(
                    "playwright_fetch_success",
                    url=url,
                    size=len(content),
                    has_boxscore_links="boxscore" in content.lower(),
                    preview=preview[:150],
                )
                return content

            except Exception as e:
                logger.warning("playwright_page_error", url=url, error=str(e))
                return None
            finally:
                context.close()
                browser.close()

    except ImportError:
        logger.warning("playwright_not_installed")
    except Exception as e:
        logger.warning("playwright_error", url=url, error=str(e))

    # Fallback: try cloudscraper (works on some environments)
    try:
        import cloudscraper

        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )
        response = scraper.get(url, timeout=30)
        response.raise_for_status()
        content = response.text
        logger.info("cloudscraper_fetch_success", url=url, size=len(content))
        return content
    except Exception as e:
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

    html = _fetch_page(schedule_url)
    if html is None:
        logger.error("schedule_fetch_error", sport=sport.name)
        return []

    soup = BeautifulSoup(html, "html.parser")

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

    for i, sport in enumerate(sports):
        try:
            # Add delay between sport requests to avoid rate limiting
            if i > 0:
                time.sleep(2)

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
