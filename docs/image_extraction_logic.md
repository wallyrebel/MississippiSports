# Image Extraction Logic

## Overview
One of the most complex components of this automation is reliably finding high-quality images for articles. Since RSS feeds vary wildly in how they present images (media tags, enclosures, or just HTML body content), we use a "waterfall" priority system.

**File:** `src/rss_to_wp/images/rss_extractor.py`

## The Extraction Waterfall

The system attempts to find an image in the following order. As soon as a method succeeds, it stops and uses that image.

### 1. Feed-Specific Default Image
**Use Case:** Small schools or feeds that rarely have images (e.g., "Coahoma CC").
- **Config:** Defined in `feeds.yaml` with the `default_image` key (e.g., `assets/nemcc_default.jpg`).
- **Logic:** If configured, the system loads this local file immediately. It does **not** attempt to fetch remote images if a default is forced, ensuring reliability for problem feeds.

### 2. RSS Media Tags (`<media:content>` / `<enclosure>`)
**Use Case:** Standard RSS feeds (Sidearm, WordPress).
- **Logic:** The parser looks for standard RSS media extensions.
- **Sidearm Nuance:** Sidearm feeds often provide a `<media:content>` tag with a high-res URL. This is preferred over the `<enclosure>` which might be a thumbnail.
- **Trusted Hosts:** If the URL is from a known Sidearm domain (listed in `known_image_hosts` in `rss_extractor.py`), the downloader uses specific headers to bypass 403 Forbidden errors.

### 3. HTML Scraping (Open Graph)
**Use Case:** Feeds that include the link but no image in the RSS XML itself.
- **Logic:**
    1. The system fetches the full article HTML from the `link` provided in the RSS item.
    2. It parses the `<head>` for `<meta property="og:image" content="...">`.
    3. Use this as the image source.
- **Risk:** This requires an extra HTTP request and is slower. It also relies on the site not blocking the scraper.

### 4. Stock Photo Fallback (Pexels / Unsplash)
**Use Case:** No image found in RSS or on the page (or extraction failed).
- **Config:** Requires `PEXELS_API_KEY` or `UNSPLASH_ACCESS_KEY` in `.env`.
- **Logic:**
    1. The system takes the **cleaned title** of the article (removing boilerplate like "Men's Basketball").
    2. It searches the stock photo API.
    3. It selects the first relevant result.
- **Note:** This is a last resort. Images may be generic (e.g., a generic basketball hoop for a specific game result).

## Trusted Hosts List
found in `src/rss_to_wp/images/rss_extractor.py`

The `known_image_hosts` list is critical. Many athletic sites (Sidearm especially) block requests from generic Python User-Agents.
- **If a host is in this list:** We behave like a standard web browser (Mozilla/5.0).
- **If not:** We use standard requests behavior.

**When adding a new school:** If you see "Image download failed: 403 Forbidden" in the logs, add the domain to this list.
