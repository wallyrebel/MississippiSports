"""Configuration for NEMCC box score scraping.

Defines all NEMCC sports with their codes, types, and season identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass


# NEMCC base domain
NEMCC_BASE_URL = "https://www.nemccathletics.com"

# NEMCC Tiger logo — used as featured image for all box score articles
NEMCC_LOGO_URL = (
    "https://cdn.prestosports.com/action/cdn/"
    "q8dj2yjpp4coqxqz/images/setup/2015/NEMCC_WEB.png"
)

# Local path to cached logo (relative to project root)
NEMCC_LOGO_LOCAL = "assets/nemcc_tiger_logo.png"

# WordPress category for all NEMCC box score articles
NEMCC_CATEGORY = "NEMCC Sports"

# Default tags applied to all NEMCC articles
NEMCC_DEFAULT_TAGS = ["NEMCC", "Northeast Mississippi", "Tigers", "Box Score"]


@dataclass
class SportConfig:
    """Configuration for a single NEMCC sport."""

    code: str           # URL path code (e.g., "bsb")
    name: str           # Human-readable name (e.g., "Baseball")
    sport_type: str     # Stat parsing type: baseball, basketball, football, volleyball
    season: str         # Academic year (e.g., "2025-26")
    enabled: bool = True

    @property
    def schedule_url(self) -> str:
        """Build the schedule page URL for this sport."""
        return f"{NEMCC_BASE_URL}/sports/{self.code}/{self.season}/schedule"

    @property
    def boxscores_base_url(self) -> str:
        """Base URL for box scores of this sport."""
        return f"{NEMCC_BASE_URL}/sports/{self.code}/{self.season}/boxscores/"


# All NEMCC sports with box score support
NEMCC_SPORTS: list[SportConfig] = [
    SportConfig(
        code="bsb",
        name="Baseball",
        sport_type="baseball",
        season="2025-26",
    ),
    SportConfig(
        code="sball",
        name="Softball",
        sport_type="softball",
        season="2025-26",
    ),
    SportConfig(
        code="mbkb",
        name="Men's Basketball",
        sport_type="basketball",
        season="2025-26",
    ),
    SportConfig(
        code="wbkb",
        name="Women's Basketball",
        sport_type="basketball",
        season="2025-26",
    ),
    SportConfig(
        code="fball",
        name="Football",
        sport_type="football",
        season="2025-26",
    ),
    SportConfig(
        code="wvball",
        name="Volleyball",
        sport_type="volleyball",
        season="2025-26",
    ),
]


def get_sport_by_code(code: str) -> SportConfig | None:
    """Look up a sport config by its URL code."""
    for sport in NEMCC_SPORTS:
        if sport.code == code:
            return sport
    return None
