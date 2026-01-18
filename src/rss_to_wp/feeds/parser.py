"""RSS feed parsing with web scraping fallback."""

from __future__ import annotations

import re
from typing import Any, Optional

import feedparser
import requests
from bs4 import BeautifulSoup

from rss_to_wp.utils import get_logger

logger = get_logger("feeds.parser")


def parse_feed(url: str) -> Optional[dict[str, Any]]:
    """Parse an RSS/Atom feed from URL.

    Args:
        url: URL of the RSS feed.

    Returns:
        Parsed feed dictionary or None if parsing failed.
    """
    logger.info("parsing_feed", url=url)

    try:
        feed = feedparser.parse(url)

        # Check for parsing errors
        if feed.bozo and feed.bozo_exception:
            logger.warning(
                "feed_parse_warning",
                url=url,
                error=str(feed.bozo_exception),
            )
            # Continue anyway - feedparser often recovers

        if not feed.entries:
            logger.info("feed_empty", url=url)
            return feed

        logger.info(
            "feed_parsed",
            url=url,
            entry_count=len(feed.entries),
            feed_title=feed.feed.get("title", "Unknown"),
        )

        return feed

    except Exception as e:
        logger.error("feed_parse_error", url=url, error=str(e))
        return None


def scrape_article_content(url: str) -> Optional[str]:
    """Scrape full article content from a source URL.

    Args:
        url: URL of the article to scrape.

    Returns:
        Article content as text, or None if scraping failed.
    """
    if not url:
        return None
        
    logger.info("scraping_article", url=url)
    
    try:
        response = requests.get(
            url,
            timeout=(10, 30),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, "html.parser")
        
        # Remove unwanted elements
        for element in soup(["script", "style", "nav", "header", "footer", "aside", "iframe", "noscript"]):
            element.decompose()
        
        # Try to find the main article content using common selectors
        article_content = None
        
        # Athletics sites often use these selectors
        content_selectors = [
            "article .article-body",
            ".article-content",
            ".story-body",
            ".article__body",
            "[itemprop='articleBody']",
            ".node-content",
            ".post-content",
            ".entry-content",
            "article",
            ".content-body",
            "main",
            "#content",
        ]
        
        for selector in content_selectors:
            element = soup.select_one(selector)
            if element:
                # Get text content
                text = element.get_text(separator=" ", strip=True)
                # Only use if it has substantial content
                if len(text) > 200:
                    article_content = text
                    logger.info("scraped_content", length=len(text), selector=selector)
                    break
        
        # If no article content found, try to get body text
        if not article_content:
            body = soup.find("body")
            if body:
                text = body.get_text(separator=" ", strip=True)
                if len(text) > 200:
                    article_content = text
                    logger.info("scraped_body_fallback", length=len(text))
        
        # Clean up whitespace
        if article_content:
            article_content = re.sub(r'\s+', ' ', article_content)
            article_content = article_content.strip()
        
        return article_content
        
    except requests.RequestException as e:
        logger.warning("scrape_request_error", url=url, error=str(e))
        return None
    except Exception as e:
        logger.warning("scrape_error", url=url, error=str(e))
        return None


def get_entry_content(entry: dict[str, Any], scrape_if_short: bool = True) -> str:
    """Extract the best available content from an RSS entry.

    Prefers full content over summary. If content is too short and
    scrape_if_short is True, attempts to scrape the full article from source URL.

    Args:
        entry: RSS entry dictionary.
        scrape_if_short: If True, scrape source URL when RSS content is short.

    Returns:
        Content string (may be HTML).
    """
    # Try content first (usually full article)
    rss_content = ""
    if "content" in entry and entry["content"]:
        # content is usually a list
        contents = entry["content"]
        if isinstance(contents, list) and len(contents) > 0:
            rss_content = contents[0].get("value", "")

    # Fall back to summary
    if not rss_content and "summary" in entry:
        rss_content = entry.get("summary", "")

    # Last resort: description
    if not rss_content:
        rss_content = entry.get("description", "")
    
    # Check if RSS content is too short - if so, try to scrape the source
    # Strip HTML to get actual text length
    clean_content = re.sub(r'<[^>]+>', '', rss_content)
    clean_content = re.sub(r'\s+', ' ', clean_content).strip()
    
    if scrape_if_short and len(clean_content) < 500:
        # Try to get the source URL and scrape
        source_url = entry.get("link", "")
        if not source_url and "links" in entry and entry["links"]:
            for link in entry["links"]:
                if link.get("rel") == "alternate" or link.get("type") == "text/html":
                    source_url = link.get("href")
                    break
            if not source_url:
                source_url = entry["links"][0].get("href", "")
        
        if source_url:
            scraped_content = scrape_article_content(source_url)
            if scraped_content and len(scraped_content) > len(clean_content):
                logger.info("using_scraped_content", 
                           rss_length=len(clean_content),
                           scraped_length=len(scraped_content))
                return scraped_content
    
    return rss_content



def get_entry_link(entry: dict[str, Any]) -> Optional[str]:
    """Get the link URL from an RSS entry.

    Args:
        entry: RSS entry dictionary.

    Returns:
        Link URL or None.
    """
    # Direct link attribute
    if "link" in entry and entry["link"]:
        return entry["link"]

    # Links list
    if "links" in entry and entry["links"]:
        for link in entry["links"]:
            if link.get("rel") == "alternate" or link.get("type") == "text/html":
                return link.get("href")
        # Return first link as fallback
        return entry["links"][0].get("href")

    return None


def get_entry_title(entry: dict[str, Any]) -> str:
    """Get the title from an RSS entry.

    Args:
        entry: RSS entry dictionary.

    Returns:
        Title string.
    """
    return entry.get("title", "Untitled")
