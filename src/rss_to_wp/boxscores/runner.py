"""Orchestrate the NEMCC box score pipeline.

Ties together: discovery → scraping → AI rewriting → WordPress publishing.
Operates independently from the RSS feed pipeline.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from openai import OpenAI

from rss_to_wp.boxscores.config import (
    NEMCC_CATEGORY,
    NEMCC_DEFAULT_TAGS,
    NEMCC_SPORTS,
    SportConfig,
)
from rss_to_wp.boxscores.discovery import discover_all_boxscores
from rss_to_wp.boxscores.prompts import get_boxscore_prompt
from rss_to_wp.boxscores.scraper import BoxScoreData, scrape_boxscore
from rss_to_wp.config import AppSettings
from rss_to_wp.storage import DedupeStore
from rss_to_wp.utils import get_logger
from rss_to_wp.wordpress import WordPressClient

logger = get_logger("boxscores.runner")

# Counter for logo rotation — persists across articles in a single run
_logo_counter = 0


def _get_nemcc_logo_path(config_dir: Path) -> Optional[Path]:
    """Get the next NEMCC logo path, rotating through available logos.

    Looks for files matching 'nemcc_logo_*.png' (or .jpg) in the assets/ dir.
    Rotates through them sequentially with each call.

    Args:
        config_dir: Project root directory.

    Returns:
        Path to the next logo file, or None if no logos found.
    """
    global _logo_counter

    assets_dir = config_dir / "assets"
    if not assets_dir.exists():
        return None

    # Find all NEMCC logo files
    logo_files = sorted(
        [
            f
            for f in assets_dir.iterdir()
            if f.is_file()
            and f.stem.startswith("nemcc_logo")
            and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
        ]
    )

    if not logo_files:
        return None

    # Rotate through logos
    logo_path = logo_files[_logo_counter % len(logo_files)]
    _logo_counter += 1

    logger.info(
        "using_nemcc_logo",
        logo=logo_path.name,
        index=(_logo_counter - 1) % len(logo_files),
        total_logos=len(logo_files),
    )

    return logo_path


def _rewrite_boxscore(
    stats_text: str,
    sport_type: str,
    api_key: str,
    model: str = "gpt-5-mini",
    fallback_model: str = "gpt-4.1-nano",
) -> Optional[dict]:
    """Rewrite box score stats into an AP-style article using OpenAI.

    Args:
        stats_text: Formatted stats text from BoxScoreData.to_stats_text().
        sport_type: Sport type for prompt selection.
        api_key: OpenAI API key.
        model: Primary model.
        fallback_model: Fallback model if primary fails.

    Returns:
        Dict with headline, body, excerpt, tags — or None on failure.
    """
    system_prompt = get_boxscore_prompt(sport_type)
    user_message = f"Write a game recap article based on this box score data:\n\n{stats_text}"

    client = OpenAI(api_key=api_key)

    for attempt_model in [model, fallback_model]:
        try:
            logger.info(
                "rewriting_boxscore",
                model=attempt_model,
                stats_length=len(stats_text),
            )

            response = client.chat.completions.create(
                model=attempt_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=2000,
                temperature=0.4,
            )

            response_text = response.choices[0].message.content or ""

            # Parse JSON from response
            result = _parse_json_response(response_text)
            if result:
                logger.info(
                    "boxscore_rewrite_success",
                    model=attempt_model,
                    headline=result.get("headline", "")[:50],
                )
                return result

            logger.warning(
                "boxscore_rewrite_parse_failed",
                model=attempt_model,
            )

        except Exception as e:
            logger.warning(
                "boxscore_rewrite_error",
                model=attempt_model,
                error=str(e),
            )
            continue

    return None


def _parse_json_response(text: str) -> Optional[dict]:
    """Parse JSON from AI response, handling markdown code blocks."""
    # Try direct JSON parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from code block
    import re

    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding JSON object in text
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1:
        try:
            return json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass

    return None


def run_boxscores(
    settings: AppSettings,
    dry_run: bool = False,
    single_sport: Optional[str] = None,
    project_dir: Optional[Path] = None,
) -> tuple[int, int, int]:
    """Run the full NEMCC box score pipeline.

    Args:
        settings: Application settings.
        dry_run: If True, process without publishing.
        single_sport: If set, only process this sport (by name).
        project_dir: Project root directory (for finding logo assets).

    Returns:
        Tuple of (processed_count, skipped_count, error_count).
    """
    logger.info(
        "starting_boxscore_pipeline",
        dry_run=dry_run,
        single_sport=single_sport,
    )

    # Determine project directory for assets
    if project_dir is None:
        project_dir = Path(__file__).parent.parent.parent.parent

    # Filter sports if single_sport specified
    sports = [s for s in NEMCC_SPORTS if s.enabled]
    if single_sport:
        sports = [
            s for s in sports if s.name.lower() == single_sport.lower()
        ]
        if not sports:
            logger.error("sport_not_found", name=single_sport)
            return (0, 0, 1)

    # Initialize components
    dedupe_store = DedupeStore()

    wp_client = None
    if not dry_run:
        wp_client = WordPressClient(
            base_url=settings.wordpress_base_url,
            username=settings.wordpress_username,
            password=settings.wordpress_app_password,
            default_status=settings.wordpress_post_status,
        )

    # Step 1: Discover all box scores
    all_boxscores = discover_all_boxscores(sports)
    logger.info("total_discovered", count=len(all_boxscores))

    processed = 0
    skipped = 0
    errors = 0

    for bs_info in all_boxscores:
        url = bs_info["url"]
        dedup_key = f"boxscore:{url}"

        # Step 2: Check dedup
        if dedupe_store.is_processed(dedup_key):
            skipped += 1
            continue

        try:
            # Step 3: Scrape box score
            data = scrape_boxscore(
                url=url,
                sport_type=bs_info["sport_type"],
                sport_name=bs_info["sport_name"],
            )

            if not data:
                logger.warning("scrape_failed", url=url)
                errors += 1
                continue

            # Step 4: Generate stats text
            stats_text = data.to_stats_text()

            if len(stats_text.strip()) < 50:
                # Not enough data — use raw text
                if data.raw_text:
                    stats_text = data.raw_text
                else:
                    logger.warning("insufficient_data", url=url)
                    errors += 1
                    continue

            # Step 5: Rewrite with AI
            rewritten = _rewrite_boxscore(
                stats_text=stats_text,
                sport_type=bs_info["sport_type"],
                api_key=settings.openai_api_key,
                model="gpt-5-mini",              # Primary model
                fallback_model="gpt-4.1-nano",    # Fallback if primary fails
            )

            if not rewritten:
                logger.error("rewrite_failed", url=url)
                errors += 1
                continue

            # Step 6: Handle logo (rotate through available logos)
            featured_media_id = None
            logo_path = _get_nemcc_logo_path(project_dir)

            if not dry_run and wp_client and logo_path and logo_path.exists():
                with open(logo_path, "rb") as f:
                    logo_bytes = f.read()

                featured_media_id = wp_client.upload_media(
                    image_bytes=logo_bytes,
                    filename=logo_path.name,
                    alt_text="NEMCC Tigers",
                )

            # Step 7: Create/get category and tags
            category_id = None
            tag_ids = []

            if not dry_run and wp_client:
                category_id = wp_client.get_or_create_category(NEMCC_CATEGORY)

                # Combine default tags with AI-generated tags
                ai_tags = rewritten.get("tags", [])
                if isinstance(ai_tags, list):
                    all_tags = list(set(NEMCC_DEFAULT_TAGS + ai_tags))
                else:
                    all_tags = NEMCC_DEFAULT_TAGS
                tag_ids = wp_client.get_or_create_tags(all_tags)

            # Step 8: Publish or log
            if dry_run:
                logger.info(
                    "dry_run_boxscore",
                    headline=rewritten["headline"][:60],
                    body_length=len(rewritten.get("body", "")),
                    sport=bs_info["sport_name"],
                    score=f"{data.nemcc_score}-{data.opponent_score}",
                    opponent=data.opponent_name,
                    logo=logo_path.name if logo_path else "none",
                )
                processed += 1
            else:
                if wp_client:
                    post = wp_client.create_post(
                        title=rewritten["headline"],
                        content=rewritten.get("body", ""),
                        excerpt=rewritten.get("excerpt", ""),
                        category_id=category_id,
                        tag_ids=tag_ids,
                        featured_media_id=featured_media_id,
                        source_url=url,
                    )

                    if post:
                        # Mark as processed
                        dedupe_store.mark_processed(
                            entry_key=dedup_key,
                            feed_url=f"nemcc-boxscore:{bs_info['sport_code']}",
                            entry_title=rewritten["headline"],
                            entry_link=url,
                            wp_post_id=post.get("id"),
                            wp_post_url=post.get("link"),
                        )
                        processed += 1

                        logger.info(
                            "boxscore_published",
                            headline=rewritten["headline"][:60],
                            wp_url=post.get("link"),
                        )
                    else:
                        errors += 1
                else:
                    errors += 1

            # Rate limit between articles
            time.sleep(2)

        except Exception as e:
            logger.error(
                "boxscore_processing_error",
                url=url,
                error=str(e),
            )
            errors += 1
            continue

    logger.info(
        "boxscore_pipeline_complete",
        processed=processed,
        skipped=skipped,
        errors=errors,
    )

    return (processed, skipped, errors)
