# NEMCC Box Score Integration

## Overview

This module automatically discovers, scrapes, and rewrites NEMCC box scores into AP-style game recap articles. It operates **independently** from the RSS feed pipeline and runs as a separate CLI command.

## Sports Covered

| Sport | Code | Box Score Format |
|-------|------|------------------|
| Baseball | `bsb` | Batting + Pitching stats |
| Softball | `sball` | Batting + Pitching stats |
| Men's Basketball | `mbkb` | Shooting + Rebounds + Assists |
| Women's Basketball | `wbkb` | Shooting + Rebounds + Assists |
| Football | `fball` | Passing + Rushing + Receiving |
| Volleyball | `wvball` | Kills + Assists + Digs + Blocks |

## How It Works

### 1. Discovery
Scrapes each sport's schedule page at:
```
https://www.nemccathletics.com/sports/{code}/{season}/schedule
```
Extracts all box score links matching the pattern:
```
/sports/{code}/{season}/boxscores/{YYYYMMDD}_{uid}.xml
```

### 2. Deduplication
Uses the **same SQLite database** (`data/processed.db`) as the RSS pipeline.
Box score entries are keyed as `boxscore:{url}` to prevent duplicate articles.

### 3. Stat Scraping
Fetches each box score page and parses:
- Game header (teams, date, location)
- Linescore (score by period)
- Player stat tables (sport-specific columns)
- Team totals

### 4. AI Rewriting
Sends structured stats to GPT with sport-specific prompts that:
- **ONLY use facts from the box score** — no invented narratives
- Write in AP-style professional sports journalism tone
- Produce: headline, HTML body, excerpt, and tags

### 5. Publishing
- Creates WordPress post with the rewritten article
- Attaches a **rotating NEMCC tiger logo** as featured image
- Categorized under "NEMCC Sports"
- Auto-tagged with sport, team names, and player names

## Usage

```bash
# Process all NEMCC sports
python -m rss_to_wp boxscores

# Dry run (no publishing)
python -m rss_to_wp boxscores --dry-run

# Single sport only
python -m rss_to_wp boxscores --single-sport "Baseball"
```

## Logo Rotation

Place NEMCC logos in the `assets/` directory with the naming prefix `nemcc_logo`:

```
assets/
├── nemcc_logo_1.png    # Tiger head
├── nemcc_logo_2.png    # NE Tigers yellow circle
└── nemcc_logo_3.png    # NE Tigers gold circle
```

The system rotates through these logos alphabetically, using a different one for each article published in a run.

## Architecture

```
src/rss_to_wp/boxscores/
├── __init__.py      # Package exports
├── config.py        # Sport definitions (6 sports)
├── discovery.py     # Schedule page scraping
├── scraper.py       # Box score HTML → structured data
├── prompts.py       # Sport-specific AI prompts
└── runner.py        # Pipeline orchestrator
```

The module uses these **existing** components:
- `DedupeStore` — SQLite dedup (same DB as RSS feeds)
- `WordPressClient` — REST API publishing
- OpenAI API — via direct client (with model waterfall)

## Automation

Runs automatically via GitHub Actions after the RSS pipeline:
```yaml
- name: Process NEMCC Box Scores
  run: python -m rss_to_wp boxscores
```

Uses `if: always()` so it runs even if the RSS step fails.
