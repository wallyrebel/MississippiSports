import sys
sys.path.insert(0, "c:/Users/myers/OneDrive/Desktop/MississippiSports/src")

from rss_to_wp.images.rss_extractor import is_valid_image_url, find_rss_image, scrape_image_from_url
from rss_to_wp.images.downloader import download_image
import feedparser

# Test NEMCC image URL validation
nemcc_image_url = "https://www.nemccathletics.com/sports/mbkb/2025-26/photos/NE_MBB_20252026_TeamPhoto_WEB.jpg?max_width=160&max_height=120"

print("=" * 60)
print("Testing NEMCC Image URL Validation")
print("=" * 60)
print(f"URL: {nemcc_image_url}")
print(f"is_valid_image_url: {is_valid_image_url(nemcc_image_url)}")

# Test parsing the actual RSS feed
print("\n" + "=" * 60)
print("Testing NEMCC RSS Feed Image Extraction")
print("=" * 60)

feed_url = "https://www.nemccathletics.com/sports/mbkb/headlines-featured?feed=rss_2.0"
feed = feedparser.parse(feed_url)

if feed.entries:
    entry = feed.entries[0]
    print(f"Entry title: {entry.get('title', 'N/A')}")
    print(f"Entry link: {entry.get('link', 'N/A')}")
    
    # Check what image fields are available
    print(f"\nmedia_content: {entry.get('media_content', 'NOT FOUND')}")
    print(f"media_thumbnail: {entry.get('media_thumbnail', 'NOT FOUND')}")
    print(f"enclosures: {entry.get('enclosures', 'NOT FOUND')}")
    
    # Try find_rss_image
    rss_image = find_rss_image(entry, "https://www.nemccathletics.com")
    print(f"\nfind_rss_image result: {rss_image}")
    
    if rss_image:
        print(f"is_valid_image_url for RSS image: {is_valid_image_url(rss_image)}")
    
    # Try scraping the article
    article_url = entry.get('link')
    print(f"\nTrying scrape_image_from_url({article_url})...")
    scraped = scrape_image_from_url(article_url)
    print(f"Scraped image: {scraped}")

else:
    print("No entries in feed!")
