"""Image download and fallback orchestration."""

from __future__ import annotations

import re
from io import BytesIO
from typing import Optional
from urllib.parse import urlparse

import requests
from PIL import Image

from rss_to_wp.images.pexels import PexelsClient
from rss_to_wp.images.unsplash import UnsplashClient
from rss_to_wp.utils import get_logger

logger = get_logger("images.downloader")


def download_image(
    url: str,
    max_size_mb: float = 5.0,
    timeout: tuple[int, int] = (10, 30),
) -> Optional[tuple[bytes, str, str]]:
    """Download an image from URL.

    Args:
        url: Image URL to download.
        max_size_mb: Maximum file size in MB.
        timeout: Request timeout (connect, read).

    Returns:
        Tuple of (image_bytes, filename, content_type) or None on failure.
    """
    logger.info("downloading_image", url=url)

    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            stream=True,
        )
        response.raise_for_status()

        # Check content length
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_size_mb * 1024 * 1024:
            logger.warning("image_too_large", url=url, size_mb=int(content_length) / (1024 * 1024))
            return None

        # Read content
        content = response.content

        # Validate it's actually an image
        try:
            img = Image.open(BytesIO(content))
            img.verify()
        except Exception as e:
            logger.warning("invalid_image", url=url, error=str(e))
            return None

        # Determine filename and type
        content_type = response.headers.get("Content-Type", "image/jpeg")
        filename = _extract_filename(url, content_type)

        logger.info(
            "image_downloaded",
            url=url,
            size_bytes=len(content),
            content_type=content_type,
        )

        return (content, filename, content_type)

    except requests.exceptions.RequestException as e:
        logger.error("image_download_error", url=url, error=str(e))
        return None
    except Exception as e:
        logger.error("image_download_error", url=url, error=str(e))
        return None


def _extract_filename(url: str, content_type: str) -> str:
    """Extract or generate a filename from URL or content type.

    Args:
        url: Image URL.
        content_type: Content-Type header.

    Returns:
        Filename string.
    """
    valid_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    
    parsed = urlparse(url)
    
    # 1. Try to get from URL path if it has a valid image extension
    path = parsed.path
    if path:
        filename = path.split("/")[-1].split("?")[0]
        if filename and "." in filename:
            ext = "." + filename.rsplit(".", 1)[-1].lower()
            if ext in valid_exts:
                return filename

    # 2. Try to find extension in query string (e.g., image_path=...jpg)
    if parsed.query:
        # Look for common patterns like .jpg in the query
        for part in parsed.query.split("&"):
            if "=" in part:
                value = part.split("=", 1)[1]
                # If value is a path/url, get the end
                if "/" in value:
                    value = value.split("/")[-1]
                
                if "." in value:
                    ext = "." + value.rsplit(".", 1)[-1].lower()
                    if ext in valid_exts:
                        return value

    # 3. Generate based on content type
    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
    }
    # Clean content type (remove charset etc)
    content_type = content_type.split(";")[0].strip().lower()
    ext = ext_map.get(content_type, ".jpg")

    # Use a hash of the URL to ensure uniqueness but consistency
    import hashlib
    url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
    return f"featured-image-{url_hash}{ext}"



def extract_keywords(text: str, max_words: int = 5) -> str:
    """Extract keywords from text for image search.

    Args:
        text: Source text (title, feed name, etc.).
        max_words: Maximum number of keywords.

    Returns:
        Cleaned keyword string.
    """
    # Remove common stop words
    stop_words = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
        "be", "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "must", "shall", "can", "need",
        "this", "that", "these", "those", "it", "its", "their", "our", "your",
        "new", "announces", "released", "says", "reports", "today", "week",
    }

    # Clean text
    text = re.sub(r"[^\w\s]", " ", text.lower())
    words = text.split()

    # Filter stop words and short words
    keywords = [w for w in words if w not in stop_words and len(w) > 2]

    # Return top N unique words
    seen = set()
    unique_keywords = []
    for w in keywords:
        if w not in seen:
            seen.add(w)
            unique_keywords.append(w)
        if len(unique_keywords) >= max_words:
            break

    return " ".join(unique_keywords)


def find_fallback_image(
    title: str,
    feed_name: str,
    pexels_key: Optional[str] = None,
    unsplash_key: Optional[str] = None,
) -> Optional[dict]:
    """Find a fallback image from stock photo providers.

    Uses sport-specific search terms for athletics content.
    Tries Pexels first, then Unsplash.

    Args:
        title: Article title for keyword extraction.
        feed_name: Feed name for additional context.
        pexels_key: Pexels API key (optional).
        unsplash_key: Unsplash access key (optional).

    Returns:
        Dictionary with url, photographer, source, alt_text, or None.
    """
    if not pexels_key and not unsplash_key:
        logger.warning("no_fallback_providers_configured")
        return None

    # Detect sport from title and feed name for better search
    combined_text = f"{title} {feed_name}".lower()
    
    # Sport-specific keywords mapping
    sport_queries = {
        "basketball": ["basketball", "mbball", "wbball", "hoops"],
        "baseball": ["baseball"],
        "softball": ["softball"],
        "football": ["football"],
        "soccer": ["soccer", "msoc", "wsoc"],
        "volleyball": ["volleyball", "vball"],
        "tennis": ["tennis", "mten", "wten"],
        "golf": ["golf", "mgolf", "wgolf"],
        "track": ["track", "mtrack", "wtrack", "cross country", "mcross", "wcross"],
        "swimming": ["swimming", "swim"],
    }
    
    # Find matching sport
    detected_sport = None
    for sport, keywords in sport_queries.items():
        for keyword in keywords:
            if keyword in combined_text:
                detected_sport = sport
                break
        if detected_sport:
            break
    
    # Build search query based on detected sport
    if detected_sport:
        # Use sport-specific search for cleaner results
        query = f"college {detected_sport} sport"
        logger.info("fallback_image_sport_search", query=query, detected_sport=detected_sport)
    else:
        # Fall back to generic sports or extracted keywords
        query = extract_keywords(f"{title} {feed_name}")
        if not query:
            query = "college sports athletics"
        logger.info("fallback_image_search", query=query)

    # Try Pexels first (more generous rate limit)
    if pexels_key:
        try:
            pexels = PexelsClient(pexels_key)
            result = pexels.search(query)
            if result:
                return result
        except Exception as e:
            logger.warning("pexels_fallback_error", error=str(e))

    # Try Unsplash
    if unsplash_key:
        try:
            unsplash = UnsplashClient(unsplash_key)
            result = unsplash.search(query)
            if result:
                return result
        except Exception as e:
            logger.warning("unsplash_fallback_error", error=str(e))

    logger.warning("no_fallback_image_found", query=query)
    return None

