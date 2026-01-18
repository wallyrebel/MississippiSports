"""Extract images from RSS entries and source URLs."""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from rss_to_wp.utils import get_logger

logger = get_logger("images.rss_extractor")

# Valid image extensions
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

# Valid image MIME types
IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
}


def scrape_image_from_url(url: str) -> Optional[str]:
    """Scrape the main image from a source article URL.
    
    Checks og:image meta tags and common image patterns.
    
    Args:
        url: URL of the article to scrape.
        
    Returns:
        Image URL or None.
    """
    if not url:
        return None
    
    logger.info("scraping_image_from_url", url=url)
    
    try:
        response = requests.get(
            url,
            timeout=(10, 30),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, "html.parser")
        
        # 1. Check og:image meta tag (highest priority)
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            image_url = og_image["content"]
            if is_valid_image_url(image_url):
                logger.info("found_og_image", url=image_url)
                return image_url
        
        # 2. Check twitter:image meta tag
        twitter_image = soup.find("meta", attrs={"name": "twitter:image"})
        if twitter_image and twitter_image.get("content"):
            image_url = twitter_image["content"]
            if is_valid_image_url(image_url):
                logger.info("found_twitter_image", url=image_url)
                return image_url
        
        # 3. Look for featured/hero images in common athletics site patterns
        hero_selectors = [
            ".hero-image img",
            ".featured-image img",
            ".article-image img",
            ".story-image img",
            "article img",
            ".post-thumbnail img",
            ".wp-post-image",
            "figure img",
        ]
        
        for selector in hero_selectors:
            img = soup.select_one(selector)
            if img:
                src = img.get("src") or img.get("data-src")
                if src:
                    # Resolve relative URLs
                    if not src.startswith(("http://", "https://")):
                        src = urljoin(url, src)
                    if is_valid_image_url(src):
                        logger.info("found_hero_image", url=src, selector=selector)
                        return src
        
        logger.debug("no_image_found_in_source", url=url)
        return None
        
    except requests.RequestException as e:
        logger.warning("image_scrape_request_error", url=url, error=str(e))
        return None
    except Exception as e:
        logger.warning("image_scrape_error", url=url, error=str(e))
        return None

def is_valid_image_url(url: str) -> bool:
    """Check if URL appears to be a valid image.

    Args:
        url: URL to validate.

    Returns:
        True if URL looks like an image.
    """
    if not url:
        return False

    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False

        # Check extension
        path_lower = parsed.path.lower()
        for ext in IMAGE_EXTENSIONS:
            if path_lower.endswith(ext):
                return True

        # Some CDN URLs don't have extensions but are still valid
        # Allow URLs from known image CDNs
        known_image_hosts = [
            "pexels.com",
            "unsplash.com",
            "cloudinary.com",
            "imgix.net",
            "wp.com",
            "wordpress.com",
            "flickr.com",
            "staticflickr.com",
        ]
        for host in known_image_hosts:
            if host in parsed.netloc.lower():
                return True

        return False

    except Exception:
        return False


def find_rss_image(entry: dict[str, Any], base_url: str = "") -> Optional[str]:
    """Find an image URL from an RSS entry.

    Checks multiple sources in order of preference:
    1. media:content
    2. media:thumbnail
    3. enclosure with image type
    4. <img> tags in content/summary

    Args:
        entry: RSS entry dictionary from feedparser.
        base_url: Base URL for resolving relative URLs.

    Returns:
        Image URL or None if no image found.
    """
    image_url = None

    # 1. Check media:content (media_content in feedparser)
    if "media_content" in entry and entry["media_content"]:
        for media in entry["media_content"]:
            url = media.get("url", "")
            media_type = media.get("type", "")
            medium = media.get("medium", "")

            # Check if it's an image
            if media_type in IMAGE_MIME_TYPES or medium == "image":
                if is_valid_image_url(url):
                    image_url = url
                    logger.debug("found_media_content_image", url=url)
                    break
            elif is_valid_image_url(url):
                image_url = url
                logger.debug("found_media_content_image", url=url)
                break

    # 2. Check media:thumbnail (media_thumbnail in feedparser)
    if not image_url and "media_thumbnail" in entry and entry["media_thumbnail"]:
        for thumb in entry["media_thumbnail"]:
            url = thumb.get("url", "")
            if is_valid_image_url(url):
                image_url = url
                logger.debug("found_media_thumbnail", url=url)
                break

    # 3. Check enclosures
    if not image_url and "enclosures" in entry and entry["enclosures"]:
        for enclosure in entry["enclosures"]:
            enc_type = enclosure.get("type", "")
            url = enclosure.get("href", "") or enclosure.get("url", "")
            if enc_type in IMAGE_MIME_TYPES or is_valid_image_url(url):
                if url:
                    image_url = url
                    logger.debug("found_enclosure_image", url=url)
                    break

    # 4. Check links for image type
    if not image_url and "links" in entry and entry["links"]:
        for link in entry["links"]:
            if link.get("type", "") in IMAGE_MIME_TYPES:
                url = link.get("href", "")
                if url:
                    image_url = url
                    logger.debug("found_link_image", url=url)
                    break

    # 5. Parse images from content/summary HTML
    if not image_url:
        html_content = ""
        if "content" in entry and entry["content"]:
            html_content = entry["content"][0].get("value", "")
        elif "summary" in entry:
            html_content = entry.get("summary", "")
        elif "description" in entry:
            html_content = entry.get("description", "")

        if html_content:
            image_url = extract_first_image_from_html(html_content, base_url)

    if image_url:
        logger.info("rss_image_found", url=image_url)
    else:
        logger.debug("no_rss_image_found", entry_title=entry.get("title", "unknown"))

    return image_url


def extract_first_image_from_html(html: str, base_url: str = "") -> Optional[str]:
    """Extract the first image URL from HTML content.

    Args:
        html: HTML content string.
        base_url: Base URL for resolving relative URLs.

    Returns:
        Image URL or None.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Find all img tags
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if not src:
                continue

            # Skip common placeholder/tracking patterns
            skip_patterns = [
                "pixel",
                "spacer",
                "blank",
                "1x1",
                "tracking",
                "beacon",
                "analytics",
                "gravatar",
                "avatar",
            ]
            if any(pattern in src.lower() for pattern in skip_patterns):
                continue

            # Resolve relative URLs
            if base_url and not src.startswith(("http://", "https://")):
                src = urljoin(base_url, src)

            if is_valid_image_url(src):
                logger.debug("found_html_image", url=src)
                return src

    except Exception as e:
        logger.warning("html_image_extraction_error", error=str(e))

    return None
