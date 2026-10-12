"""One authorized story. Fail closed; never retry a mutation automatically.

This transport deliberately cannot publish an arbitrary article. Retire its
workflow after the verified publication. Editorial/source semantics belong to
the reviewing task; fixed copy and supplied image digests bound this operation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlparse, urljoin
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup
from PIL import Image

SITE = "https://sportsmississippi.com"
HEADLINE = "Tupelo Football Player Killed In Weekend Crash"
SLUG = "tupelo-football-player-alden-wade-killed-weekend-crash"
EVENT = "alden-wade-tupelo-crash-2026-10-11"
MARKER = f"<!-- sportsms-news:{EVENT} -->"
POLICE = "https://www.facebook.com/252815570209253/posts/1585980470226083"
FEED = "https://fetchrss.com/feed/1vcaujD2G3c21vcatkBil4m3.rss"
WTVA = "https://www.wtva.com/2026/10/11/tupelo-high-school-football-player-killed-overnight-crash/?outputType=amp"
PHOTO_SHA = "af060be733a8921aec8e6b90ca514079e55052bc25f49bc86d88778a3bfe7f79"
PHOTO_PATH = "news/assets/alden-wade-original.jpg"
ORIGINAL_FILENAME = "846809076_1412247560886392_5401629991584046713_n.jpg"
MEDIA_SLUG = "alden-wade-portrait-" + PHOTO_SHA[:16]
ALT = "Alden Wade smiling in his Tupelo football uniform."
EXCERPT = "Tupelo football player Alden Wade died in a single-vehicle crash Sunday, Oct. 11. Police and the school community responded to the loss."
QUOTE = "No Words. Phenomenal young man with the perfect smile. Definition of a selfless person. You will be missed AW!"
BODY = (
    '<p>Tupelo High School football player Alden Wade died in a single-vehicle crash early Sunday, Oct. 11, in Tupelo.</p>\n'
    f'<p><a href="{POLICE}">Tupelo police said</a> officers responded at approximately 1:11 a.m. to the 4900 block of Cliff Gookin Boulevard. The crash resulted in one fatality, and department accident reconstructionists responded to investigate.</p>\n'
    f'<p>The police statement did not identify the person who died. <a href="{html.escape(WTVA, quote=True)}">WTVA, citing the Lee County Coroner’s Office,</a> identified the victim as Wade.</p>\n'
    '<p>Tupelo head football coach Ty Hardin remembered Wade for his character and smile.</p>\n'
    f'<p>“{QUOTE}” Hardin said.</p>\n'
    '<p>In a statement, Tupelo High School and its football team said they were heartbroken by Wade’s death and expressed support for his family, friends, teammates and classmates.</p>\n'
    '<p>Police said additional information may be released when appropriate.</p>'
)
POLICE_EXCERPT = "On Sunday, October 11, 2026, at approximately 1:11 a.m., officers with the Tupelo Police Department responded to a single-vehicle traffic crash in the 4900 block of Cliff Gookin Boulevard. The crash resulted in one fatality. Accident reconstructionists with the Tupelo Police Department responded and worked the scene. Additional information may be released when appropriate."
WTVA_EXCERPTS = (
    "A Tupelo High School football player died in an overnight crash Sunday, Oct. 11.",
    "According to Lee County Coroner Carolyn Green, the crash happened around 1 a.m. on Cliff Gookin Boulevard.",
    "The Lee County Coroner’s Office identified the victim as 19-year-old Alden Wade of Tupelo.",
)
BODY_SHA = hashlib.sha256(BODY.encode()).hexdigest()


class NewsError(RuntimeError):
    """Sanitized error, never HTTP response bodies or credentials."""


def require(condition, message):
    if not condition:
        raise NewsError(message)


def plain(value):
    return " ".join(BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True).split())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pixels(data):
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        require(image.size == (765, 906), "Portrait dimensions changed")
        return digest(image.convert("RGB").tobytes())


def validate(data, now=None):
    now = now or datetime.now(timezone.utc)
    require(data.get("version") == 1 and data.get("event_id") == EVENT,
            "Only the explicitly authorized event is supported")
    require(data.get("headline") == HEADLINE and data.get("slug") == SLUG,
            "Exact headline and approved topic slug required")
    require(data.get("html") == BODY and data.get("article_sha256") == BODY_SHA,
            "Copy differs from the bounded reviewed article")
    require(data.get("excerpt") == EXCERPT and data.get("featured_alt") == ALT,
            "Unreviewed excerpt or alt text")
    require(data.get("image_path") == PHOTO_PATH and data.get("image_sha256") == PHOTO_SHA,
            "Only the supplied unchanged portrait is supported")
    require(data.get("source_urls") == [POLICE, WTVA], "Reporting source identities changed")
    require(data.get("quote_provenance") == "publisher_supplied_verbatim"
            and data.get("school_statement_provenance") == "inspected_supplied_images",
            "Do not invent independently verified quote provenance")
    require(data.get("authorized") is True and isinstance(data.get("publish"), bool),
            "Explicit authorization and publication mode required")
    require(isinstance(data.get("parent_reviewed"), bool), "Review flag required")
    try:
        checked = datetime.fromisoformat(data["verified_at"].replace("Z", "+00:00"))
        require(checked.tzinfo is not None and timedelta(minutes=-5) <= now - checked <= timedelta(hours=18),
                "Stale or future source review")
    except (KeyError, ValueError, TypeError):
        raise NewsError("Invalid source review timestamp") from None
    if data["publish"]:
        require(data["parent_reviewed"] is True, "Parent final copy/image review required")
        attestation = data.get("preflight", {})
        require(type(attestation.get("run_id")) is int and attestation["run_id"] > 0
                and re.fullmatch(r"[0-9a-f]{40}", attestation.get("commit", ""))
                and attestation.get("article_sha256") == BODY_SHA
                and attestation.get("image_sha256") == PHOTO_SHA,
                "Exact managed preflight must be reviewed before publication")
    recovery = data.get("recovery_post_id")
    require(recovery is None or type(recovery) is int and recovery > 0,
            "Recovery must name the previously created post")


def safe_site_url(url):
    parsed = urlparse(url)
    require(parsed.scheme == "https" and parsed.hostname in ("sportsmississippi.com", "www.sportsmississippi.com")
            and not parsed.username and not parsed.password and parsed.port in (None, 443),
            "Unexpected public site URL")
    return url


def public_get(session, url):
    try:
        response = session.get(url, timeout=(10, 40), allow_redirects=False)
        require(response.status_code == 200, "Public source or verification URL unavailable")
        return response
    except requests.RequestException:
        raise NewsError("Public read unavailable") from None


def verify_sources(public):
    try:
        feed = ET.fromstring(public_get(public, FEED).content)
    except ET.ParseError:
        raise NewsError("Police feed unreadable") from None
    items = [item for item in feed.findall(".//item") if item.findtext("link") == POLICE]
    require(len(items) == 1, "Exact primary police post missing or ambiguous")
    require(items[0].findtext("pubDate") == "Sun, 11 Oct 2026 16:21:59 +0000",
            "Police source date identity changed")
    require(POLICE_EXCERPT in plain(items[0].findtext("description", "")),
            "Primary police facts changed")
    police_text = plain(items[0].findtext("description", ""))
    require("Alden" not in police_text and "Wade" not in police_text,
            "Re-review police identification wording")
    soup = BeautifulSoup(public_get(public, WTVA).text, "html.parser")
    for element in soup(["script", "style", "nav", "header", "footer"]):
        element.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    require(all(excerpt in text for excerpt in WTVA_EXCERPTS), "Coroner/player identity bridge changed")
    return {"police_original": POLICE, "police_transport": FEED, "identification_report": WTVA,
            "quote_provenance": "publisher_supplied_verbatim", "checked": True}


class Publisher:
    def __init__(self, auth, public, output, photo):
        self.auth, self.public, self.output, self.photo = auth, public, Path(output), photo
        self.actions = []
        self.audit = {"queries": [], "statuses": {}}

    def request(self, method, endpoint, **kwargs):
        try:
            response = self.auth.request(method, f"{SITE}/wp-json/wp/v2/{endpoint}",
                                         timeout=(10, 45), allow_redirects=False, **kwargs)
            require(200 <= response.status_code < 300,
                    f"WordPress {method} {endpoint} failed (HTTP {response.status_code})")
            return response
        except requests.RequestException:
            raise NewsError(f"WordPress {method} {endpoint} outcome unavailable") from None

    def read(self, endpoint, **kwargs):
        try:
            return self.request("GET", endpoint, **kwargs).json()
        except ValueError:
            raise NewsError("WordPress read returned invalid JSON") from None

    def write(self, endpoint, **kwargs):
        # Record the attempt before I/O. No retry adapter or request loop exists.
        action = {"method": "POST", "endpoint": endpoint, "state": "attempted"}
        self.actions.append(action)
        self.save_actions()
        try:
            value = self.request("POST", endpoint, **kwargs).json()
            require(type(value.get("id")) is int and value["id"] > 0, "Write response lacked an ID")
            action.update(state="confirmed", id=value["id"])
            return value
        except (ValueError, NewsError):
            action["state"] = "uncertain_or_failed"
            raise NewsError(f"Stop: {endpoint} write failed or uncertain; reconcile the same post/media before another run") from None
        finally:
            self.save_actions()

    def save_actions(self):
        self.output.mkdir(parents=True, exist_ok=True)
        (self.output / "actions.json").write_text(json.dumps(self.actions, indent=2) + "\n")

    def discover_statuses(self, endpoint):
        try:
            schema = self.request("OPTIONS", endpoint).json()
        except ValueError:
            raise NewsError("REST schema unavailable") from None
        choices = []
        for route in schema.get("endpoints", []):
            if "GET" in route.get("methods", []) and "status" in route.get("args", {}):
                choices = route["args"]["status"].get("items", {}).get("enum", [])
                break
        statuses = [s for s in choices if s != "any"]
        required = {"publish", "future", "draft", "pending", "private", "trash"} if endpoint == "posts" else {"inherit", "private", "trash"}
        require(required <= set(statuses), "All supported post/media statuses could not be established")
        self.audit["statuses"][endpoint] = statuses
        return statuses

    def collect(self, endpoint, query, statuses):
        # Explicit repeated array parameters avoid ambiguous PHP scalar parsing.
        params = [("status[]", status) for status in statuses]
        params += [("context", "edit"), ("per_page", 100), ("orderby", "id"), ("order", "asc")]
        params += list(query.items())
        items, total, pages = [], None, None
        page = 1
        while True:
            response = self.request("GET", endpoint, params=params + [("page", page)])
            try:
                batch = response.json()
                this_total = int(response.headers["X-WP-Total"])
                this_pages = int(response.headers["X-WP-TotalPages"])
            except (KeyError, ValueError, TypeError):
                raise NewsError("Exhaustive lookup pagination unavailable") from None
            require(isinstance(batch, list) and 0 <= this_pages <= 1000, "Lookup pagination invalid")
            if total is None:
                total, pages = this_total, this_pages
            require((total, pages) == (this_total, this_pages), "Lookup changed while paginating; re-review")
            items.extend(batch)
            if page >= pages:
                break
            page += 1
        require(len(items) == total and len({item["id"] for item in items}) == total,
                "Incomplete or unstable duplicate lookup")
        self.audit["queries"].append({"endpoint": endpoint, "query": query, "total": total, "pages": pages})
        return items

    def reconcile(self):
        # Complete every identity query over every schema-supported status.
        posts = {}
        post_statuses = self.discover_statuses("posts")
        queries = [{"slug": SLUG}] + [{"search": q} for q in (
            SLUG, EVENT, HEADLINE, "Alden Wade", "Cliff Gookin", "1585980470226083",
            "tupelo-high-school-football-player-killed-overnight-crash")]
        for query in queries:
            for post in self.collect("posts", query, post_statuses):
                posts[post["id"]] = post
        matches = []
        for post in posts.values():
            text = plain(post.get("title", {}).get("raw", "") + " " + post.get("content", {}).get("raw", "")).casefold()
            raw = post.get("content", {}).get("raw", "")
            if (post.get("slug", "").startswith(SLUG) or MARKER in raw
                    or plain(post.get("title", {}).get("raw", "")) == HEADLINE
                    or POLICE in raw or WTVA.split("?")[0] in raw
                    or "alden wade" in text
                    or "cliff gookin" in text):
                matches.append(post)
        require(len(matches) <= 1, "Multiple event/source/post identities found; manual reconciliation required")
        media = {}
        media_statuses = self.discover_statuses("media")
        for query in [{"slug": MEDIA_SLUG}] + [{"search": q} for q in (
                MEDIA_SLUG, PHOTO_SHA[:16], ORIGINAL_FILENAME.rsplit(".", 1)[0], "Alden Wade")]:
            for item in self.collect("media", query, media_statuses):
                media[item["id"]] = item
        if matches:
            for item in self.collect("media", {"parent": matches[0]["id"]}, media_statuses):
                media[item["id"]] = item
            if matches[0].get("featured_media"):
                item = self.read(f"media/{matches[0]['featured_media']}", params={"context": "edit"})
                media[item["id"]] = item
        verified_media = []
        for item in media.values():
            raw = self.original_image(item)
            if digest(raw) == PHOTO_SHA:
                require(item.get("status") == "inherit", "Matching portrait is private/trashed; manual reconciliation required")
                require(pixels(raw) == pixels(self.photo), "Matching original portrait pixels changed")
                verified_media.append(item)
            else:
                # Similar names alone do not establish a reusable image identity.
                require(item.get("slug") != MEDIA_SLUG,
                        "Deterministic media identity has different original bytes")
        require(len(verified_media) <= 1, "Multiple matching original portraits found; reconcile before writing")
        result = {"post": matches[0] if matches else None,
                  "media": verified_media[0] if verified_media else None,
                  "candidate_post_ids": sorted(posts), "candidate_media_ids": sorted(media),
                  "matching_post_ids": [post["id"] for post in matches],
                  "matching_media_ids": [item["id"] for item in verified_media],
                  "all_statuses_checked": True, **self.audit}
        (self.output / "reconciliation.json").write_text(json.dumps(result, indent=2) + "\n")
        return result

    def original_url(self, media):
        url = safe_site_url(media.get("source_url", ""))
        original = media.get("media_details", {}).get("original_image")
        if original:
            require("/" not in original and ".." not in original, "Invalid original media filename")
            url = safe_site_url(urljoin(url, original))
        return url

    def original_image(self, media):
        return public_get(self.public, self.original_url(media)).content

    def snapshot(self, post):
        return {key: post.get(key) for key in ("id", "slug", "status", "modified_gmt", "title", "content", "featured_media", "link", "excerpt", "meta", "categories")}

    def ensure_owned_draft(self, post, expected_media=None):
        require(post.get("slug") == SLUG and post.get("status") == "draft"
                and post.get("content", {}).get("raw") == BODY + "\n" + MARKER
                and post.get("title", {}).get("raw") == HEADLINE,
                "Existing draft differs from the owned reviewed article")
        if expected_media is not None:
            require(post.get("featured_media") == expected_media, "Draft featured association changed")

    def category(self):
        values = self.read("categories", params={"slug": "prep-sports", "per_page": 100})
        require(isinstance(values, list) and len(values) == 1, "Existing Prep Sports category unavailable")
        return values[0]["id"]

    def publish(self, data, preflight):
        existing, media = preflight["post"], preflight["media"]
        if existing and existing.get("status") == "publish":
            require(MARKER in existing.get("content", {}).get("raw", ""),
                    "An independently created event article already exists; no overwrite authorized")
            return self.verify_public(existing, existing["featured_media"], operation="already_published")
        if existing:
            require(data.get("recovery_post_id") == existing["id"],
                    "Existing event draft needs explicit same-post recovery ID")
            self.ensure_owned_draft(existing)
            post = existing
        else:
            require(data.get("recovery_post_id") is None, "Recovery post missing; never create a replacement")
            try:
                post = self.write("posts", json={"title": HEADLINE, "slug": SLUG, "status": "draft",
                        "content": BODY + "\n" + MARKER, "excerpt": EXCERPT,
                        "comment_status": "closed", "categories": [self.category()]})
            except NewsError:
                # Read-only reconciliation may locate the lost draft response.
                self.reconcile()
                raise
            self.ensure_owned_draft(post, expected_media=0)
        (self.output / "owned-post.json").write_text(json.dumps(self.snapshot(post), indent=2) + "\n")
        if not media:
            try:
                media = self.write("media", params={"post": post["id"], "slug": MEDIA_SLUG},
                    data=self.photo, headers={"Content-Type": "image/jpeg",
                    "Content-Disposition": f'attachment; filename="{MEDIA_SLUG}.jpg"'})
            except NewsError:
                self.reconcile()
                raise
        require(digest(self.original_image(media)) == PHOTO_SHA, "Uploaded original portrait bytes changed")
        media_id = media["id"]
        # Reuse does not reparent media away from another article.
        require(media.get("post", 0) in (0, post["id"]), "Portrait belongs to another post; manual review required")
        if media.get("alt_text") != ALT or media.get("post") != post["id"]:
            media = self.write(f"media/{media_id}", json={"alt_text": ALT, "title": "Alden Wade",
                                "caption": "Alden Wade. Photo supplied to Sports Mississippi.", "post": post["id"]})
        require(media.get("alt_text") == ALT and media.get("post") == post["id"],
                "Portrait alt/parent association unconfirmed")
        current = self.read(f"posts/{post['id']}", params={"context": "edit"})
        self.ensure_owned_draft(current)
        require(current.get("modified_gmt") == post.get("modified_gmt"),
                "Draft changed while attaching image; re-review same post")
        meta = {"_seopress_titles_title": HEADLINE, "_seopress_titles_desc": EXCERPT,
                "_seopress_robots_index": "", "_seopress_robots_follow": "",
                "_seopress_robots_imageindex": "", "_seopress_robots_canonical": ""}
        ready = self.write(f"posts/{post['id']}", json={"featured_media": media_id, "meta": meta})
        self.ensure_owned_draft(ready, expected_media=media_id)
        require(all(ready.get("meta", {}).get(key) == value for key, value in meta.items()),
                "Article SEO fields not confirmed")
        check = self.read(f"posts/{post['id']}", params={"context": "edit"})
        require(self.snapshot(check) == self.snapshot(ready), "Draft changed before publish; stop")
        try:
            published = self.write(f"posts/{post['id']}", json={"status": "publish"})
        except NewsError:
            observed = self.read(f"posts/{post['id']}", params={"context": "edit"})
            (self.output / "uncertain-post.json").write_text(json.dumps(self.snapshot(observed), indent=2) + "\n")
            raise
        return self.verify_public(published, media_id, operation="published")

    def verify_public(self, post, media_id, operation):
        require(post.get("status") == "publish" and post.get("slug") == SLUG and media_id > 0,
                "Published article identity unconfirmed")
        canonical = safe_site_url(post.get("link", ""))
        visible = public_get(self.public, f"{SITE}/wp-json/wp/v2/posts/{post['id']}").json()
        require(visible.get("status") == "publish" and visible.get("slug") == SLUG
                and visible.get("featured_media") == media_id
                and plain(visible.get("title", {}).get("rendered", "")) == HEADLINE
                and plain(visible.get("content", {}).get("rendered", "")) == plain(BODY),
                "Public REST title/body/image differs from reviewed article")
        page = public_get(self.public, canonical)
        soup = BeautifulSoup(page.text, "html.parser")
        require(any(plain(h1) == HEADLINE for h1 in soup.find_all("h1")), "Public H1 differs")
        require(soup.title and plain(soup.title) == HEADLINE, "Public SEO title differs")
        desc = soup.find("meta", attrs={"name": "description"})
        require(desc and desc.get("content") == EXCERPT, "Public SEO description differs")
        links = soup.find_all("link", rel="canonical")
        require(len(links) == 1 and links[0].get("href") == canonical, "Self-canonical unconfirmed")
        robots = " ".join(tag.get("content", "") for tag in soup.find_all("meta")
                          if tag.get("name", "").casefold() in ("robots", "googlebot"))
        robots += " " + page.headers.get("X-Robots-Tag", "")
        require("noindex" not in robots.casefold() and "none" not in robots.casefold(),
                "Published page is not indexable")
        page_text = plain(soup)
        require(all(plain(p) in page_text for p in BeautifulSoup(BODY, "html.parser").find_all("p")),
                "Public page body incomplete")
        hrefs = {a.get("href") for a in soup.find_all("a")}
        require(POLICE in hrefs and WTVA in hrefs, "Public reporting-source links missing")
        media = public_get(self.public, f"{SITE}/wp-json/wp/v2/media/{media_id}").json()
        image_url = self.original_url(media)
        original = self.original_image(media)
        require(digest(original) == PHOTO_SHA and pixels(original) == pixels(self.photo),
                "Public original portrait bytes or pixels differ")
        require(media.get("alt_text") == ALT, "Public media alt differs")
        images = soup.find_all("img")
        require(any(image.get("alt") == ALT and (image_url in str(image)
                    or MEDIA_SLUG in str(image)) for image in images), "Portrait not displayed on public page")
        robots_file = public_get(self.public, SITE + "/robots.txt").text
        require(not re.search(r"(?im)^Disallow:\s*/\s*$", robots_file), "Site robots blocks indexing")
        return {"state": "published", "operation": operation, "post_id": post["id"], "url": canonical,
                "featured_media": media_id, "image_url": image_url, "image_sha256": PHOTO_SHA,
                "pixel_sha256": pixels(original), "article_sha256": BODY_SHA,
                "public_verification": {"body": True, "source_links": True, "h1": True,
                    "seo_title": True, "description": True, "self_canonical": True,
                    "indexable": True, "original_image_bytes_and_pixels": True}}


def run(data, output, offline=False, auth=None, public=None):
    validate(data)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    photo = Path(PHOTO_PATH).read_bytes()
    require(digest(photo) == PHOTO_SHA, "Supplied original image hash differs")
    pixel_sha = pixels(photo)
    (output / "article.html").write_text(BODY + "\n")
    review = {"headline": HEADLINE, "slug": SLUG, "html": BODY, "excerpt": EXCERPT,
              "alt": ALT, "article_sha256": BODY_SHA, "image_sha256": PHOTO_SHA,
              "pixel_sha256": pixel_sha, "source_urls": [POLICE, WTVA]}
    (output / "review.json").write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n")
    if offline:
        require(not data["publish"], "Offline mode cannot publish")
        return {"state": "offline_validated", "authenticated": False, **review}
    public = public or requests.Session()
    public.headers["User-Agent"] = "SportsMississippi-ReviewedNews/1.0"
    sources = verify_sources(public)
    if auth is None:
        require(os.environ.get("WORDPRESS_BASE_URL", "").rstrip("/") == SITE,
                "Existing managed WordPress target differs")
        require(os.environ.get("WORDPRESS_USERNAME") and os.environ.get("WORDPRESS_APP_PASSWORD"),
                "Existing managed authentication unavailable")
        auth = requests.Session()
        auth.auth = (os.environ["WORDPRESS_USERNAME"], os.environ["WORDPRESS_APP_PASSWORD"])
    publisher = Publisher(auth, public, output, photo)
    try:
        # Read-only edit-context identity check establishes authentication before lookup.
        me = publisher.read("users/me", params={"context": "edit", "_fields": "id,capabilities"})
        require(type(me.get("id")) is int and me["id"] > 0, "Authenticated identity unconfirmed")
        require(all(me.get("capabilities", {}).get(capability) is True
                    for capability in ("edit_posts", "publish_posts", "upload_files")),
                "Existing managed account lacks required publishing capabilities")
        preflight = publisher.reconcile()
        publisher.category()  # Never create taxonomy.
        if not data["publish"]:
            return {"state": "authenticated_preflight", "authenticated": True, "sources_checked": sources,
                    "matching_post_ids": preflight["matching_post_ids"],
                    "matching_media_ids": preflight["matching_media_ids"], "all_statuses_checked": True,
                    "actions": [], **review}
        require(os.environ.get("GITHUB_RUN_ATTEMPT", "1") == "1", "Automatic mutation reruns are disabled")
        result = publisher.publish(data, preflight)
        return {**result, "sources_checked": sources, "all_statuses_checked": True,
                "actions": publisher.actions}
    finally:
        publisher.save_actions()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("intake")
    parser.add_argument("--output", default="news-output")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    try:
        result = run(json.loads(Path(args.intake).read_text()), output, args.offline)
        code = 0
    except (NewsError, OSError, ValueError) as error:
        result = {"state": "failed", "reason": str(error) if isinstance(error, NewsError)
                  else "Input or verification unavailable; reconcile before retry"}
        code = 1
    (output / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("html",)}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
