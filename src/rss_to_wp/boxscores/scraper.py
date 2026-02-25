"""Scrape and parse NEMCC box score pages into structured data.

Handles different stat table formats for each sport type:
- Baseball/Softball: batting + pitching stats
- Basketball: shooting + rebounding stats
- Football: passing + rushing + receiving stats
- Volleyball: attacking + serving + blocking stats
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup, Tag

from rss_to_wp.utils import get_logger

logger = get_logger("boxscores.scraper")


@dataclass
class BoxScoreData:
    """Structured box score data from a single game."""

    # Game info
    sport_name: str = ""
    sport_type: str = ""
    game_date: str = ""              # YYYYMMDD format
    game_date_display: str = ""      # Human-readable date
    location: str = ""
    boxscore_url: str = ""

    # Teams and score
    home_team: str = ""
    away_team: str = ""
    home_score: str = ""
    away_score: str = ""
    nemcc_is_home: bool = True

    # Linescore (inning/quarter/half/set scores)
    linescore: dict[str, Any] = field(default_factory=dict)

    # Player stats — list of dicts per team
    nemcc_stats: list[dict[str, str]] = field(default_factory=list)
    opponent_stats: list[dict[str, str]] = field(default_factory=list)

    # Pitching stats (baseball/softball only)
    nemcc_pitching: list[dict[str, str]] = field(default_factory=list)
    opponent_pitching: list[dict[str, str]] = field(default_factory=list)

    # Team totals row
    nemcc_totals: dict[str, str] = field(default_factory=dict)
    opponent_totals: dict[str, str] = field(default_factory=dict)

    # Raw text for AI fallback
    raw_text: str = ""

    @property
    def nemcc_won(self) -> bool:
        """Check if NEMCC won the game."""
        try:
            return int(self.nemcc_score) > int(self.opponent_score)
        except (ValueError, TypeError):
            return False

    @property
    def nemcc_score(self) -> str:
        """Get NEMCC's score."""
        return self.home_score if self.nemcc_is_home else self.away_score

    @property
    def opponent_score(self) -> str:
        """Get the opponent's score."""
        return self.away_score if self.nemcc_is_home else self.home_score

    @property
    def opponent_name(self) -> str:
        """Get the opponent's name."""
        return self.away_team if self.nemcc_is_home else self.home_team

    def to_stats_text(self) -> str:
        """Convert structured data to a text summary for AI rewriting.

        Returns a clear, factual text representation of all game stats.
        """
        lines = []
        lines.append(f"Sport: {self.sport_name}")
        lines.append(f"Date: {self.game_date_display}")
        if self.location:
            lines.append(f"Location: {self.location}")
        lines.append("")

        # Score
        result = "won" if self.nemcc_won else "lost"
        lines.append(
            f"Northeast Mississippi Community College (NEMCC) {result} "
            f"{self.nemcc_score}-{self.opponent_score} "
            f"against {self.opponent_name}."
        )
        lines.append("")

        # Linescore
        if self.linescore:
            lines.append("Score by period:")
            for team, scores in self.linescore.items():
                lines.append(f"  {team}: {scores}")
            lines.append("")

        # NEMCC player stats
        if self.nemcc_stats:
            lines.append("NEMCC Player Stats:")
            for player in self.nemcc_stats:
                stat_parts = [f"{k}: {v}" for k, v in player.items() if k != "name" and v]
                if stat_parts:
                    lines.append(f"  {player.get('name', 'Unknown')}: {', '.join(stat_parts)}")
            lines.append("")

        # NEMCC pitching (baseball/softball)
        if self.nemcc_pitching:
            lines.append("NEMCC Pitching:")
            for pitcher in self.nemcc_pitching:
                stat_parts = [f"{k}: {v}" for k, v in pitcher.items() if k != "name" and v]
                if stat_parts:
                    lines.append(f"  {pitcher.get('name', 'Unknown')}: {', '.join(stat_parts)}")
            lines.append("")

        # NEMCC totals
        if self.nemcc_totals:
            total_parts = [f"{k}: {v}" for k, v in self.nemcc_totals.items() if v]
            if total_parts:
                lines.append(f"NEMCC Team Totals: {', '.join(total_parts)}")
                lines.append("")

        # Opponent player stats
        if self.opponent_stats:
            lines.append(f"{self.opponent_name} Player Stats:")
            for player in self.opponent_stats:
                stat_parts = [f"{k}: {v}" for k, v in player.items() if k != "name" and v]
                if stat_parts:
                    lines.append(f"  {player.get('name', 'Unknown')}: {', '.join(stat_parts)}")
            lines.append("")

        # Opponent pitching
        if self.opponent_pitching:
            lines.append(f"{self.opponent_name} Pitching:")
            for pitcher in self.opponent_pitching:
                stat_parts = [f"{k}: {v}" for k, v in pitcher.items() if k != "name" and v]
                if stat_parts:
                    lines.append(f"  {pitcher.get('name', 'Unknown')}: {', '.join(stat_parts)}")
            lines.append("")

        return "\n".join(lines)


def scrape_boxscore(url: str, sport_type: str, sport_name: str) -> Optional[BoxScoreData]:
    """Fetch and parse a box score page into structured data.

    Args:
        url: Full URL to the box score page.
        sport_type: Sport type for parser selection (baseball, basketball, etc).
        sport_name: Display name of the sport.

    Returns:
        BoxScoreData with extracted stats, or None on failure.
    """
    logger.info("scraping_boxscore", url=url, sport=sport_name)

    content = None

    # Try cloudscraper first
    try:
        import cloudscraper

        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )
        response = scraper.get(url, timeout=30)
        response.raise_for_status()
        content = response.text
    except Exception:
        pass

    # Fallback: plain requests with browser headers
    if content is None:
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            content = response.text
        except requests.RequestException as e:
            logger.error("boxscore_fetch_error", url=url, error=str(e))
            return None

    if content is None:
        logger.error("boxscore_fetch_error", url=url)
        return None

    soup = BeautifulSoup(content, "html.parser")

    # Extract game date from URL (YYYYMMDD)
    date_match = re.search(r"/(\d{8})_", url)
    game_date = date_match.group(1) if date_match else ""

    # Initialize box score data
    data = BoxScoreData(
        sport_name=sport_name,
        sport_type=sport_type,
        game_date=game_date,
        boxscore_url=url,
    )

    # Extract raw text for AI fallback
    data.raw_text = _extract_raw_text(soup)

    # Parse game header (teams, date, location)
    _parse_game_header(soup, data)

    # Format the display date
    if game_date and len(game_date) == 8:
        month = game_date[4:6]
        day = game_date[6:8]
        year = game_date[0:4]
        data.game_date_display = f"{month}/{day}/{year}"

    # Parse stats based on sport type
    try:
        if sport_type in ("baseball", "softball"):
            _parse_baseball_stats(soup, data)
        elif sport_type == "basketball":
            _parse_basketball_stats(soup, data)
        elif sport_type == "football":
            _parse_football_stats(soup, data)
        elif sport_type == "volleyball":
            _parse_volleyball_stats(soup, data)
        else:
            logger.warning("unknown_sport_type", sport_type=sport_type)
    except Exception as e:
        logger.warning("stats_parse_error", url=url, error=str(e))
        # Still return data — we have raw text for AI fallback

    logger.info(
        "boxscore_scraped",
        sport=sport_name,
        nemcc_score=data.nemcc_score,
        opponent=data.opponent_name,
        opponent_score=data.opponent_score,
    )

    return data


def _extract_raw_text(soup: BeautifulSoup) -> str:
    """Extract cleaned text content from the box score page."""
    # Remove scripts and styles
    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.decompose()

    text = soup.get_text(separator=" ", strip=True)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    # Limit length for AI context
    return text[:8000]


def _parse_game_header(soup: BeautifulSoup, data: BoxScoreData) -> None:
    """Parse game header for teams, date, and location."""
    # Try to find team names from the page
    # Sidearm box scores put team names in various elements

    # Look for the game title (typically an h1 with date and teams)
    h1_tags = soup.find_all("h1")
    for h1 in h1_tags:
        text = h1.get_text(strip=True)
        # Match patterns like "January 29, 2026 Team A at Team B"
        # or "Team A vs Team B"
        if "northeast" in text.lower() or "nemcc" in text.lower():
            data.game_date_display = text
            break

    # Find team names from links with class containing 'team'
    team_links = soup.select("a.team-name, .boxscore-team-name a, .team-name")
    team_names = []
    for link in team_links:
        name = link.get_text(strip=True)
        if name and name not in team_names:
            team_names.append(name)

    # If we didn't find team-name elements, try the linescore header
    if len(team_names) < 2:
        # Try finding teams from linescore table
        linescore_table = soup.select_one(
            "table.linescore, .linescore-table, "
            "[class*='linescore'] table, [class*='scoring'] table"
        )
        if linescore_table:
            rows = linescore_table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                if cells:
                    name = cells[0].get_text(strip=True)
                    if name and len(name) > 2 and name not in team_names:
                        team_names.append(name)

    # If still not found, try any element with team links
    if len(team_names) < 2:
        all_links = soup.find_all("a", href=True)
        for link in all_links:
            href = link.get("href", "")
            if "/teams?" in href:
                name = link.get_text(strip=True)
                if name and name not in team_names:
                    team_names.append(name)
                    if len(team_names) >= 2:
                        break

    # Determine which team is NEMCC
    nemcc_keywords = ["northeast mississippi", "nemcc", "northeast"]
    if len(team_names) >= 2:
        if any(kw in team_names[0].lower() for kw in nemcc_keywords):
            data.nemcc_is_home = True
            data.home_team = team_names[0]
            data.away_team = team_names[1]
        elif any(kw in team_names[1].lower() for kw in nemcc_keywords):
            data.nemcc_is_home = False
            data.home_team = team_names[1]
            data.away_team = team_names[0]
        else:
            # Default: first team listed is away
            data.home_team = team_names[1] if len(team_names) > 1 else ""
            data.away_team = team_names[0]
    elif len(team_names) == 1:
        data.home_team = team_names[0]


def _parse_stat_table(table: Tag) -> tuple[list[str], list[dict[str, str]], dict[str, str]]:
    """Parse a generic stats table into headers and rows.

    Returns:
        Tuple of (headers, player_rows, totals_row)
    """
    headers: list[str] = []
    players: list[dict[str, str]] = []
    totals: dict[str, str] = {}

    # Get headers from thead or first row
    thead = table.find("thead")
    if thead:
        header_row = thead.find("tr")
        if header_row:
            headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]

    # Get body rows
    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]

    for row in rows:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue

        values = [c.get_text(strip=True) for c in cells]

        # Check if this is a totals row
        first_val = values[0].lower() if values else ""
        if first_val in ("totals", "total", "team", "team totals"):
            if headers:
                for i, h in enumerate(headers):
                    if i < len(values):
                        totals[h] = values[i]
            continue

        # Regular player row
        if headers:
            player = {}
            for i, h in enumerate(headers):
                if i < len(values):
                    player[h] = values[i]
            # Use first column as "name"
            if headers and values:
                player["name"] = values[0]
            players.append(player)
        elif values:
            # No headers — use positional
            players.append({"name": values[0], "stats": ", ".join(values[1:])})

    return headers, players, totals


def _parse_linescore(soup: BeautifulSoup, data: BoxScoreData) -> None:
    """Parse the linescore / scoring-by-period table."""
    # Look for linescore tables
    tables = soup.find_all("table")
    for table in tables:
        # Check if this looks like a linescore
        text = table.get_text(strip=True).lower()
        if any(indicator in text for indicator in ["final", "totals", "total"]):
            rows = table.find_all("tr")
            if len(rows) >= 2:
                # Check if rows contain period scores (numbers)
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    values = [c.get_text(strip=True) for c in cells]
                    if len(values) >= 3 and values[0]:
                        # Check if most values after team name are numbers
                        num_count = sum(
                            1 for v in values[1:]
                            if v.isdigit() or v == "-"
                        )
                        if num_count >= 2:
                            team_name = values[0]
                            period_scores = " | ".join(values[1:])
                            data.linescore[team_name] = period_scores

                            # Extract final score (usually last column)
                            try:
                                score = values[-1]
                                if score.isdigit():
                                    nemcc_keywords = [
                                        "northeast", "nemcc", "ne miss",
                                    ]
                                    if any(
                                        kw in team_name.lower()
                                        for kw in nemcc_keywords
                                    ):
                                        if data.nemcc_is_home:
                                            data.home_score = score
                                        else:
                                            data.away_score = score
                                    else:
                                        if data.nemcc_is_home:
                                            data.away_score = score
                                        else:
                                            data.home_score = score
                            except (IndexError, ValueError):
                                pass

                if data.linescore:
                    return  # Found it


def _parse_baseball_stats(soup: BeautifulSoup, data: BoxScoreData) -> None:
    """Parse baseball/softball box score stats."""
    _parse_linescore(soup, data)

    # Find all stat tables
    tables = soup.find_all("table")
    team_sections_found = 0

    for table in tables:
        # Check if table header indicates batting or pitching
        table_text = table.get_text(strip=True).lower()
        parent_text = ""
        parent = table.find_parent(["section", "div"])
        if parent:
            # Get just the heading text, not the whole section
            heading = parent.find(["h2", "h3", "h4"])
            if heading:
                parent_text = heading.get_text(strip=True).lower()

        headers, players, totals = _parse_stat_table(table)
        header_str = " ".join(h.lower() for h in headers)

        # Detect batting table (has AB, R, H columns)
        is_batting = any(h in header_str for h in ["ab", "r ", " h ", "rbi"])
        # Detect pitching table (has IP, ER columns)
        is_pitching = any(h in header_str for h in ["ip", "er ", "era"])

        if is_batting and players:
            nemcc_keywords = ["northeast", "nemcc"]
            is_nemcc = any(kw in parent_text for kw in nemcc_keywords)

            if not data.nemcc_stats or is_nemcc:
                if is_nemcc or team_sections_found == 0:
                    data.nemcc_stats = players
                    data.nemcc_totals = totals
                else:
                    data.opponent_stats = players
                    data.opponent_totals = totals
                team_sections_found += 1

        elif is_pitching and players:
            if not data.nemcc_pitching:
                data.nemcc_pitching = players
            else:
                data.opponent_pitching = players


def _parse_basketball_stats(soup: BeautifulSoup, data: BoxScoreData) -> None:
    """Parse basketball box score stats."""
    _parse_linescore(soup, data)

    tables = soup.find_all("table")
    team_count = 0

    for table in tables:
        headers, players, totals = _parse_stat_table(table)
        header_str = " ".join(h.lower() for h in headers)

        # Identify basketball stat table (FG, FT, PTS, REB columns)
        is_bball = any(
            h in header_str
            for h in ["fg", "pts", "reb", "ast", "fgm", "3pm", "ftm"]
        )

        if is_bball and players:
            if team_count == 0:
                data.nemcc_stats = players
                data.nemcc_totals = totals
            else:
                data.opponent_stats = players
                data.opponent_totals = totals
            team_count += 1


def _parse_football_stats(soup: BeautifulSoup, data: BoxScoreData) -> None:
    """Parse football box score stats."""
    _parse_linescore(soup, data)

    tables = soup.find_all("table")
    for table in tables:
        headers, players, totals = _parse_stat_table(table)
        header_str = " ".join(h.lower() for h in headers)

        # Detect rushing, passing, receiving tables
        is_stats = any(
            h in header_str
            for h in ["yds", "att", "comp", "car", "rec", "td"]
        )

        if is_stats and players:
            if not data.nemcc_stats:
                data.nemcc_stats = players
                data.nemcc_totals = totals
            elif not data.opponent_stats:
                data.opponent_stats = players
                data.opponent_totals = totals


def _parse_volleyball_stats(soup: BeautifulSoup, data: BoxScoreData) -> None:
    """Parse volleyball box score stats."""
    _parse_linescore(soup, data)

    tables = soup.find_all("table")
    team_count = 0

    for table in tables:
        headers, players, totals = _parse_stat_table(table)
        header_str = " ".join(h.lower() for h in headers)

        # Identify volleyball stat table (K, AST, DIG, B, SA columns)
        is_vball = any(
            h in header_str
            for h in ["kills", "aces", "digs", "blocks", "sa", " k "]
        )

        if is_vball and players:
            if team_count == 0:
                data.nemcc_stats = players
                data.nemcc_totals = totals
            else:
                data.opponent_stats = players
                data.opponent_totals = totals
            team_count += 1
