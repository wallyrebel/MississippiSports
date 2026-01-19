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

# BLOCKED domains - never use images from these (ads, adult, tracking, etc.)
BLOCKED_IMAGE_DOMAINS = {
    # Ad networks
    "doubleclick.net",
    "googlesyndication.com",
    "googleadservices.com",
    "adnxs.com",
    "adsrvr.org",
    "amazon-adsystem.com",
    "advertising.com",
    "pubmatic.com",
    "rubiconproject.com",
    "criteo.com",
    "taboola.com",
    "outbrain.com",
    # Tracking
    "facebook.com",
    "facebook.net",
    "twitter.com",
    "analytics",
    "pixel",
    "beacon",
    "tracking",
    # Adult/inappropriate
    "adult",
    "xxx",
    "porn",
    "nsfw",
    # Generic ad patterns
    "ads.",
    "ad.",
    "banner",
    "sponsor",
    # Stock photo sites (we'll use Pexels directly for fallback)
    "shutterstock",
    "istockphoto",
    "gettyimages",
}


def is_image_domain_blocked(url: str) -> bool:
    """Check if image URL is from a blocked domain.
    
    Args:
        url: URL to check.
        
    Returns:
        True if domain is blocked, False if safe.
    """
    if not url:
        return True
    
    try:
        url_lower = url.lower()
        for blocked in BLOCKED_IMAGE_DOMAINS:
            if blocked in url_lower:
                logger.debug("blocked_image_domain", url=url, blocked_pattern=blocked)
                return True
        return False
    except Exception:
        return True


def is_same_domain(source_url: str, image_url: str) -> bool:
    """Check if image URL is from the same domain as source.
    
    Args:
        source_url: The article source URL.
        image_url: The image URL to validate.
        
    Returns:
        True if same domain or trusted subdomain.
    """
    if not source_url or not image_url:
        return False
        
    try:
        source_parsed = urlparse(source_url)
        image_parsed = urlparse(image_url)
        
        source_domain = source_parsed.netloc.lower()
        image_domain = image_parsed.netloc.lower()
        
        # Remove www. prefix for comparison
        source_domain = source_domain.replace("www.", "")
        image_domain = image_domain.replace("www.", "")
        
        # Exact match
        if source_domain == image_domain:
            return True
        
        # Allow subdomains (e.g., images.example.com for example.com)
        if image_domain.endswith("." + source_domain):
            return True
        
        # Allow CDN patterns for known athletics sites
        trusted_cdn_patterns = [
            ("careyathletics.com", "sidearm"),  # Sidearm Sports CDN
            ("careyathletics.com", "sidearmsports"),
            ("careyathletics.com", "prestosports"),
        ]
        
        for site, cdn_pattern in trusted_cdn_patterns:
            if site in source_domain and cdn_pattern in image_domain:
                return True
        
        return False
        
    except Exception:
        return False


def scrape_image_from_url(url: str) -> Optional[str]:
    """Scrape the main image from a source article URL.
    
    PRIORITY ORDER:
    1. <picture><source srcset> tags (responsive images - used by athletics sites)
    2. og:image meta tag (trusted - from source page meta)
    3. twitter:image meta tag (trusted - from source page meta)  
    4. Hero/article <img> tags (must be from same domain)
    
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
        
        # 1. Check <picture><source srcset> tags (HIGHEST PRIORITY)
        # Athletics sites like careyathletics.com use responsive images
        # Example: <source media="(min-width:768px)" srcset="/images/2026/1/15/DSC_3570.jpg?width=647...">
        picture_selectors = [
            "article picture source",
            ".article-content picture source",
            ".story-content picture source", 
            ".hero-image picture source",
            ".featured-image picture source",
            "picture source",
        ]
        
        for selector in picture_selectors:
            sources = soup.select(selector)
            for source in sources:
                srcset = source.get("srcset")
                if srcset:
                    # Parse srcset - take the first URL (before any space/descriptor)
                    # Example: "/images/2026/1/15/DSC_3570.jpg?width=647&quality=80 1x, /images/... 2x"
                    first_src = srcset.split(",")[0].strip().split()[0]
                    if first_src:
                        # Resolve relative URLs
                        if not first_src.startswith(("http://", "https://")):
                            first_src = urljoin(url, first_src)
                        
                        if is_valid_image_url(first_src) and not is_image_domain_blocked(first_src):
                            logger.info("found_srcset_image", url=first_src, selector=selector)
                            return first_src
        
        # 2. Check og:image meta tag (TRUSTED - from source page meta)
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            image_url = og_image["content"]
            if is_valid_image_url(image_url) and not is_image_domain_blocked(image_url):
                logger.info("found_og_image", url=image_url)
                return image_url
            else:
                logger.debug("og_image_rejected", image_url=image_url, reason="blocked or invalid")
        
        # 3. Check twitter:image meta tag (TRUSTED - from source page meta)
        twitter_image = soup.find("meta", attrs={"name": "twitter:image"})
        if twitter_image and twitter_image.get("content"):
            image_url = twitter_image["content"]
            if is_valid_image_url(image_url) and not is_image_domain_blocked(image_url):
                logger.info("found_twitter_image", url=image_url)
                return image_url
        
        # 4. Look for featured/hero <img> tags
        # These require same-domain validation (more likely to be ads)
        hero_selectors = [
            "article img",
            ".article-content img",
            ".story-content img",
            ".hero-image img",
            ".featured-image img",
            ".article-image img",
            ".story-image img",
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
                    
                    # Strict validation for scraped img tags (same domain + not blocked)
                    if is_valid_image_url(src) and is_same_domain(url, src) and not is_image_domain_blocked(src):
                        logger.info("found_hero_image", url=src, selector=selector)
                        return src
        
        logger.debug("no_safe_image_found_in_source", url=url)
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

        # Check extension - handle query strings by looking at path only
        # Example: /images/DSC_3570.jpg?width=647 -> check .jpg
        path_lower = parsed.path.lower()
        
        # Split off any trailing slashes and check file extension
        path_parts = path_lower.rstrip('/').split('/')
        if path_parts:
            filename = path_parts[-1]
            for ext in IMAGE_EXTENSIONS:
                if ext in filename:  # Use 'in' to catch .jpg?... patterns
                    return True
        
        # Check query params for format indicators (used by image CDNs)
        # Example: ?format=jpg or ?type=jpeg or ?image_path=...jpg
        query_lower = parsed.query.lower()
        if "format=jpg" in query_lower or "format=jpeg" in query_lower or "format=png" in query_lower:
            return True
        if "type=jpg" in query_lower or "type=jpeg" in query_lower or "type=png" in query_lower:
            return True
        # BMCU/Sidearm uses image_path=/images/...jpg format
        if "image_path=" in query_lower and (".jpg" in query_lower or ".jpeg" in query_lower or ".png" in query_lower):
            return True

        # Some CDN URLs don't have extensions but are still valid
        # Allow URLs from known image CDNs and athletics sites
        known_image_hosts = [
            "pexels.com",
            "unsplash.com", 
            "cloudinary.com",
            "imgix.net",
            "wp.com",
            "wordpress.com",
            "flickr.com",
            "staticflickr.com",
            "sidearm",  # Sidearm Sports CDN used by athletics sites
            "prestosports",  # Presto Sports CDN
            "bmcusports.com",  # Blue Mountain Christian athletics
            "careyathletics.com",  # William Carey athletics
            "nwccrangers.com",  # Northwest Mississippi CC athletics
            "coahomasports.com",  # Coahoma CC athletics
            "gostatesmen.com",  # Delta State athletics
            "mvsusports.com",  # Mississippi Valley State athletics
            "alcornsports.com",  # Alcorn State athletics
            "gojsutigers.com",  # Jackson State athletics
            "southernmiss.com",  # Southern Miss athletics
            "hailstate.com",  # Mississippi State athletics
            "olemisssports.com",  # Ole Miss athletics
            "gochoctaws.com",  # Mississippi College athletics
            "blazers.belhaven.edu",  # Belhaven University athletics
            "gomajors.com",  # Millsaps College athletics
            "owlsathletics.com",  # Mississippi University for Women athletics
            "sports.hindscc.edu",  # Hinds Community College athletics
            "jcbobcats.com",  # Jones College athletics
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
