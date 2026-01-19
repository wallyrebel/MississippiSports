# Sidearm Sports Integration Guide

## Overview
Sidearm Sports is the primary platform for many of the athletic websites integrated into this project (e.g., Mississippi College, Belhaven, Millsaps, etc.). Approximately 200+ feeds in `feeds.yaml` source from Sidearm sites. Understanding this platform's structure is critical for scaling and maintenance.

## RSS Feed Structure

The standard RSS endpoint for almost all Sidearm sites is:
`https://[domain]/rss.aspx?path=[sport_code]`

### Common Sport Codes
While mostly consistent, always verify the `path` by hovering over the "RSS" icon on the specific team's verification page or testing the URL.

| Sport | Common Code | Notes |
|-------|-------------|-------|
| Men's Basketball | `mbball` | |
| Women's Basketball | `wbball` | |
| Baseball | `baseball` | Sometimes `bsb` |
| Softball | `softball` | Sometimes `sball` |
| Football | `football` | |
| Men's Soccer | `msoc` | |
| Women's Soccer | `wsoc` | |
| Volleyball | `vball` | |
| Men's Tennis | `mten` | |
| Women's Tennis | `wten` | |

## Platform Quirks

### 1. Image Extraction & Hotlinking
Sidearm sites often employ anti-hotlinking measures or redirect image requests.
- **Problem:** The `og:image` or RSS `<media:content>` URL might be valid, but requests from scripts (like Python `requests`) are often blocked or return a 403 Forbidden.
- **Solution:** We maintain a `known_image_hosts` list in `src/rss_to_wp/images/rss_extractor.py`.
- **Mechanism:** When a domain is in this list, the `download_image` function uses specific headers (spoofed User-Agent) to successfully fetch the image bytes.
- **Action:** When adding a new Sidearm school, **always** add their domain (e.g., `jcbobcats.com`) to `known_image_hosts` if image extraction fails during testing.

### 2. Article Deduplication
Sidearm often publishes the same "General Athletics" story to multiple sport feeds if it tags multiple teams (e.g., "Scholar Athletes Announced" might appear in Baseball, Soccer, and Basketball feeds).
- **Our Handling:** The `DedupeStore` (`src/rss_to_wp/storage/dedupe.py`) uses a unique key based on the article URL. Since the URL is constant even if it appears in different RSS feeds, subsequent encounters of the same article are correctly skipped as duplicates.

### 3. XML Namespaces
Sidearm RSS feeds use specific namespaces that the parser must handle:
- `s:sport_id`: Internal Sidearm sport ID.
- `s:story_id`: Internal story ID.
- `media:content`: High-quality image reference (preferred over `enclosure`).

## verification Checklist for New Sidearm Feeds
1. **Find RSS Link:** Usually at `[domain]/rss_feeds.aspx` or the footer.
2. **Verify Output:** Visit `https://[domain]/rss.aspx?path=[sport]` in a browser to ensure it returns XML, not a 404 or HTML.
3. **Add to `feeds.yaml`:** Use the `rss.aspx` URL.
4. **Update `rss_extractor.py`:** Add domain to `known_image_hosts`.
5. **Dry Run:** Run `python -m rss_to_wp run --single-feed "Feed Name" --dry-run` to confirm 200 OK on image fetching.
