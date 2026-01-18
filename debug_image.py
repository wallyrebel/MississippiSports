
import logging
import sys
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("debug_image")

# Import the code to test (I'll copy relevant parts/imports if I can't import directly, 
# but I should be able to import since I'm in the project root context usually)
sys.path.append("c:/Users/myers/OneDrive/Desktop/MississippiSports/src")

from rss_to_wp.images.rss_extractor import is_valid_image_url, scrape_image_from_url, is_image_domain_blocked

def test_url_validation():
    test_url = "https://bmcusports.com/common/controls/image_handler.aspx?thumb_prefix=rp_primary&image_path=/images/2026/1/17/59cbdbdf-6d73-4a4a-9413-506da027e0b6.jpg"
    print(f"Testing URL: {test_url}")
    
    is_blocked = is_image_domain_blocked(test_url)
    print(f"Is domain blocked? {is_blocked}")
    
    is_valid = is_valid_image_url(test_url)
    print(f"Is valid image URL? {is_valid}")
    
    if not is_valid:
        print("DEBUG: Why is it invalid?")
        parsed = urlparse(test_url)
        print(f"Scheme: {parsed.scheme}, Netloc: {parsed.netloc}")
        print(f"Path: {parsed.path}")
        print(f"Query: {parsed.query}")
        # Re-simulate logic logic
        path_lower = parsed.path.lower()
        print(f"Path lower: {path_lower}")
        
def test_scraping():
    article_url = "https://bmcusports.com/news/2026/1/17/mens-basketball-toppers-fall-to-dalton-state-in-ssac-road-game.aspx"
    print(f"\nTesting scraping for: {article_url}")
    image_url = scrape_image_from_url(article_url)
    print(f"Scraped Image URL: {image_url}")


def test_download():
    # Use the URL found in previous step or the hardcoded one
    url = "https://bmcusports.com/common/controls/image_handler.aspx?thumb_prefix=rp_primary&image_path=/images/2026/1/17/59cbdbdf-6d73-4a4a-9413-506da027e0b6.jpg"
    print(f"\nTesting download for: {url}")
    
    try:
        # Use simple requests first to see headers
        response = requests.get(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            stream=True
        )
        print(f"Status Code: {response.status_code}")
        print(f"Content-Type: {response.headers.get('Content-Type')}")
        print(f"Content-Length: {response.headers.get('Content-Length')}")
        
        if response.status_code == 200:
            print("Download successful!")
        else:
            print(f"Download failed: {response.text[:200]}")
            
    except Exception as e:
        print(f"Error downloading: {e}")

if __name__ == "__main__":
    test_url_validation()
    test_scraping()
    test_download()
