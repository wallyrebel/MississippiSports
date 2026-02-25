"""NEMCC box score scraping, parsing, and article generation.

This package discovers new box scores from NEMCC athletics schedule pages,
extracts structured game data, rewrites it into AP-style articles using AI,
and publishes to WordPress. It operates independently from the RSS pipeline.
"""

from rss_to_wp.boxscores.config import NEMCC_SPORTS, NEMCC_BASE_URL
from rss_to_wp.boxscores.discovery import discover_boxscores
from rss_to_wp.boxscores.scraper import scrape_boxscore
from rss_to_wp.boxscores.runner import run_boxscores

__all__ = [
    "NEMCC_SPORTS",
    "NEMCC_BASE_URL",
    "discover_boxscores",
    "scrape_boxscore",
    "run_boxscores",
]
