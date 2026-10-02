"""Fail-closed daily edition intake and REST publisher. No source discovery or scheduling.

The researching agent owns semantic verification of games and date evidence. This
worker rechecks fresh source excerpts, restricts dates, and renders only supplied
structured facts. It never rewrites stories or infers missing scores/player facts.
"""
from __future__ import annotations

import argparse
import html
import io
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SITE = "https://sportsmississippi.com"
CENTRAL = ZoneInfo("America/Chicago")
SOURCE_HOSTS = {
    "maxpreps.com", "alcornsportsms.com", "tippahsports.com",
    "desotocountynews.com", "sportsmississippi.com", "misshsaa.com", "mais.ms",
}
SPORTS = {
    "football", "volleyball", "basketball", "soccer", "baseball", "softball",
    "cross country", "track and field", "swimming", "tennis", "golf", "wrestling",
    "bowling", "powerlifting", "archery", "esports",
}
LABELS = {"scores": "Scores from last Night", "preview": "Games To Watch"}
STATUSES = "publish,future,draft,pending,private,trash"


class EditionError(RuntimeError):
    """Safe, non-secret failure description."""


def normalized(value):
    return " ".join(html.unescape(str(value)).split()).casefold()


def require(condition, message):
    if not condition:
        raise EditionError(message)


def safe_url(url, hosts=SOURCE_HOSTS):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    require(parsed.scheme == "https" and host in hosts and not parsed.username
            and not parsed.password and parsed.port in (None, 443), "Unapproved source URL")
    return url


def text_field(value, label, limit=180):
    require(isinstance(value, str) and 0 < len(value.strip()) <= limit,
            f"Invalid {label}")
    require(not any(ord(c) < 32 for c in value), f"Control character in {label}")
    return value.strip()


def expected_date(edition, now):
    today = now.astimezone(CENTRAL).date()
    return today - timedelta(days=1) if edition == "scores" else today


def validate(data, now):
    require(data.get("version") == 1, "Unsupported intake version")
    edition = data.get("edition")
    require(edition in LABELS, "Unknown edition")
    require(data.get("date") == expected_date(edition, now).isoformat(),
            "Stale or future covered date in Central time")
    require(isinstance(data.get("publish"), bool), "publish must be an explicit boolean")
    try:
        checked = datetime.fromisoformat(data["verified_at"].replace("Z", "+00:00"))
        require(checked.tzinfo is not None, "verified_at must include timezone")
        age = now - checked
        require(timedelta(minutes=-5) <= age <= timedelta(hours=18), "Stale source verification")
    except (KeyError, ValueError, TypeError):
        raise EditionError("Invalid verified_at timestamp") from None
    checked_sports = data.get("checked_sports")
    require(isinstance(checked_sports, list) and checked_sports
            and all(s in SPORTS for s in checked_sports), "List active sports checked")
    games = data.get("games")
    require(isinstance(games, list) and len(games) <= 300, "Invalid game list")
    seen = set()
    for game in games:
        require(game.get("sport") in checked_sports, "Game sport was not checked")
        require(game.get("state") == "MS" and game.get("level") == "high school varsity",
                "Only Mississippi high-school varsity games are accepted")
        require(game.get("date") == data["date"], "Game date differs from edition")
        require(game.get("division") in ("boys", "girls", "coed"), "Missing division")
        require(game.get("format", "matchup") in ("matchup", "meet"), "Unknown game format")
        if game.get("format") == "meet":
            game["name"] = text_field(game.get("name"), "meet name")
            schools = game.get("schools")
            require(isinstance(schools, list) and 1 <= len(schools) <= 80, "Missing meet schools")
            for school in schools:
                text_field(school, "meet school")
            require(len(set(map(normalized, schools))) == len(schools), "Duplicate meet school")
            key = (game["sport"], game["division"], normalized(game["name"]))
        else:
            for field in ("home", "away"):
                game[field] = text_field(game.get(field), field)
            require(normalized(game["home"]) != normalized(game["away"]), "Identical teams")
            # Reverse reports are the same matchup. Doubleheaders need distinct game_no.
            key = (game["sport"], game["division"],
                   tuple(sorted((normalized(game["home"]), normalized(game["away"])))),
                   game.get("game_no", 1))
        require(type(game.get("game_no", 1)) is int and 1 <= game.get("game_no", 1) <= 5,
                "Invalid game number")
        require(key not in seen, "Duplicate or conflicting matchup")
        seen.add(key)
        if edition == "scores":
            require(game.get("status") == "final", "Non-final result")
            if game.get("format") == "meet":
                results = game.get("results")
                require(isinstance(results, list) and 1 <= len(results) <= len(game["schools"]),
                        "Missing verified team meet results")
                result_schools = set()
                for result in results:
                    require(result.get("school") in game["schools"] and result["school"] not in result_schools,
                            "Invalid meet result school")
                    require(type(result.get("place")) is int and 1 <= result["place"] <= 200,
                            "Invalid team placement")
                    result_schools.add(result["school"])
            else:
                for field in ("home_score", "away_score"):
                    require(type(game.get(field)) is int and 0 <= game[field] <= 999,
                            "Missing or invalid final score")
        else:
            require(game.get("status") == "scheduled", "Cancelled or non-scheduled game")
            require(not any(k in game for k in ("home_score", "away_score")),
                    "Scores do not belong in preview")
            if game.get("start_time"):
                try:
                    start = datetime.fromisoformat(game["start_time"])
                    require(start.tzinfo is not None and start.astimezone(CENTRAL).date().isoformat()
                            == data["date"] and start > now, "Stale game time")
                except (ValueError, TypeError):
                    raise EditionError("Invalid game time") from None
        evidence = game.get("evidence", {})
        safe_url(evidence.get("url", ""))
        quote = text_field(evidence.get("excerpt"), "source excerpt", 2500)
        date_quote = text_field(evidence.get("date_excerpt"), "source date excerpt", 200)
        # These are evidence substrings, not source text to reproduce in the article.
        if game.get("format") == "meet":
            require(normalized(game["name"]) in normalized(quote), "Meet absent from evidence")
            for school in game["schools"]:
                require(normalized(school) in normalized(quote), "Meet school absent from evidence")
        else:
            for field in ("home", "away"):
                source_name = text_field(evidence.get(field + "_name", game[field]), "source team name")
                require(normalized(source_name) in normalized(quote), "Team absent from evidence")
        require(normalized(date_quote) in normalized(quote), "Date absent from evidence")
        date_formats = {data["date"], date.fromisoformat(data["date"]).strftime("%m/%d/%Y"),
                        date.fromisoformat(data["date"]).strftime("%m/%d/%y"),
                        date.fromisoformat(data["date"]).strftime("%B %d, %Y"),
                        date.fromisoformat(data["date"]).strftime("%B %-d, %Y")}
        require(any(normalized(fmt) in normalized(date_quote) for fmt in date_formats),
                "Source date evidence must explicitly identify covered date and year")
        if edition == "scores":
            require(re.search(r"\b(final|completed)\b", quote, re.I), "No final indicator in evidence")
            values = ([r["place"] for r in game["results"]] if game.get("format") == "meet"
                      else [game["home_score"], game["away_score"]])
            for value in values:
                require(re.search(rf"(?<!\d){value}(?!\d)", quote), "Score or placement absent from evidence")
        elif game.get("start_time"):
            time_quote = text_field(evidence.get("time_excerpt"), "source time excerpt", 100)
            require(normalized(time_quote) in normalized(quote), "Time absent from evidence")
    links = data.get("related_links", [])
    require(isinstance(links, list) and len(links) <= 10, "Too many internal links")
    for link in links:
        safe_url(link["url"], {"sportsmississippi.com"})
        text_field(link["title"], "internal link title")
    return data


def read_source(url, session):
    """Fetch public evidence separately; never send WordPress credentials to sources."""
    current = safe_url(url)
    for _ in range(5):
        response = session.get(current, timeout=(10, 30), allow_redirects=False)
        if response.status_code in (301, 302, 303, 307, 308):
            from urllib.parse import urljoin
            current = safe_url(urljoin(current, response.headers.get("Location", "")))
            continue
        require(response.status_code == 200, "Source unavailable; no publication")
        require(len(response.content) <= 8_000_000, "Source too large")
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return normalized(soup.get_text(" ", strip=True))
    raise EditionError("Too many source redirects")


def verify_sources(data, session):
    cache = {}
    for game in data["games"]:
        evidence = game["evidence"]
        url = evidence["url"]
        if url not in cache:
            cache[url] = read_source(url, session)
        require(normalized(evidence["excerpt"]) in cache[url],
                "Evidence no longer present in public source; no publication")
    teams = [normalized(team) for g in data["games"]
             for team in (g["schools"] if g.get("format") == "meet" else [g["home"], g["away"]])]
    for link in data.get("related_links", []):
        page = read_source(link["url"], session)
        require(any(t in page for t in teams), "Internal link does not mention a covered team")


def identity(data):
    return f"sportsms-{data['edition']}-{data['date']}"


def render(data):
    covered = date.fromisoformat(data["date"])
    day = covered.strftime("%B %-d, %Y")
    title = f"Mississippi High School {LABELS[data['edition']]} — {day}"
    groups = defaultdict(list)
    for game in data["games"]:
        groups[(game["sport"], game["division"])].append(game)
    body = [f"<!-- {identity(data)} -->",
            f"<p>Verified Mississippi high-school {'final scores' if data['edition'] == 'scores' else 'games to watch'} for {day}.</p>"]
    for (sport, division), games in sorted(groups.items()):
        body.append(f"<h2>{html.escape(sport.title())} — {division.title()}</h2><ul>")
        for game in sorted(games, key=lambda g: (g.get("away", g.get("name", "")),
                                                g.get("home", ""), g.get("game_no", 1))):
            if game.get("format") == "meet":
                line = html.escape(game["name"]) + " — "
                if data["edition"] == "scores":
                    line += "; ".join(f"{html.escape(r['school'])}: team place {r['place']}"
                                      for r in game["results"]) + " — Final team results"
                else:
                    line += ", ".join(html.escape(s) for s in game["schools"])
            elif data["edition"] == "scores":
                away, home = html.escape(game["away"]), html.escape(game["home"])
                line = f"{away} {game['away_score']}, {home} {game['home_score']} — Final"
            else:
                line = f"{html.escape(game['away'])} at {html.escape(game['home'])}"
            if data["edition"] == "preview":
                if game.get("start_time"):
                    start = datetime.fromisoformat(game["start_time"]).astimezone(CENTRAL)
                    line += f" — {start.strftime('%-I:%M %p %Z')}"
                else:
                    line += " — start time not verified"
            if game.get("game_no", 1) > 1:
                line += f" (Game {game['game_no']})"
            url = html.escape(game["evidence"]["url"], quote=True)
            label = html.escape(urlparse(url).hostname or "Source")
            body.append(f'<li>{line}. <a href="{url}" rel="noopener">Source: {label}</a></li>')
        body.append("</ul>")
    checked = ", ".join(s.title() for s in sorted(set(data["checked_sports"])))
    body.append(f"<p><em>Coverage: {len(data['games'])} verified games. Active sports checked: {html.escape(checked)}. "
                "This is a source-confirmed selection, not a complete statewide scoreboard or schedule. "
                "Unreported results, unconfirmed schedules and unavailable sources are omitted. "
                "Schedules may change.</em></p>")
    if data.get("related_links"):
        body.append("<h2>Related coverage</h2><ul>")
        for link in data["related_links"]:
            body.append(f'<li><a href="{html.escape(link["url"], quote=True)}">{html.escape(link["title"])}</a></li>')
        body.append("</ul>")
    return title, "\n".join(body)


def featured_image(data):
    """Original typography card with exact edition label and covered date."""
    image = Image.new("RGB", (1600, 900), "#102535")
    draw = ImageDraw.Draw(image)
    font_paths = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                  "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]
    def font(size):
        for path in font_paths:
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        raise EditionError("Featured image font unavailable")
    draw.rectangle((0, 0, 1600, 24), fill="#efb441")
    draw.rounded_rectangle((90, 106, 665, 172), radius=16, fill="#efb441")
    draw.text((117, 122), "MISSISSIPPI HIGH SCHOOL", font=font(32), fill="#102535")
    label = LABELS[data["edition"]]
    lines = ["Scores from", "last Night"] if data["edition"] == "scores" else ["Games To Watch"]
    for index, line in enumerate(lines):
        draw.text((90, 258 + index * 120), line, font=font(96), fill="white")
    day = date.fromisoformat(data["date"]).strftime("%B %-d, %Y")
    draw.text((94, 560), day, font=font(56), fill="#efb441")
    draw.line((90, 714, 1510, 714), fill="#3d586b", width=3)
    draw.text((94, 772), "SPORTSMISSISSIPPI.COM", font=font(32), fill="#bcd1df")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue(), f"{label} — {day}"


def public_session():
    session = requests.Session()
    session.headers.update({"User-Agent": "SportsMississippi-Editions/1.0"})
    # Retrying read-only evidence/verification is safe. Mutation session has no retries.
    session.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=1,
                  allowed_methods={"GET"}, status_forcelist=[429, 502, 503, 504])))
    return session


class Publisher:
    def __init__(self, session, public, sleeper=time.sleep):
        self.session, self.public, self.sleep = session, public, sleeper

    def api(self, method, endpoint, **kwargs):
        try:
            response = self.session.request(method, f"{SITE}/wp-json/wp/v2/{endpoint}",
                                            timeout=(10, 45), allow_redirects=False, **kwargs)
            require(200 <= response.status_code < 300, f"WordPress {method} failed (HTTP {response.status_code})")
            return response.json()
        except (requests.RequestException, ValueError):
            raise EditionError(f"WordPress {method} outcome unavailable") from None

    def lookup(self, key):
        # Authenticated all-status lookup plus marker search catches draft/renamed posts.
        found = {}
        for query in ({"slug": key}, {"search": key}):
            posts = self.api("GET", "posts", params={**query, "status": STATUSES,
                             "context": "edit", "per_page": 100})
            require(isinstance(posts, list) and len(posts) < 100, "Ambiguous duplicate lookup")
            for post in posts:
                content = post.get("content", {}).get("raw", "")
                if post.get("slug") == key or f"<!-- {key} -->" in content:
                    found[post["id"]] = post
        require(len(found) <= 1, "Multiple edition posts found; manual reconciliation required")
        return next(iter(found.values()), None)

    def reconcile(self, key):
        # A lost POST response never causes a second create attempt in this run.
        for _ in range(3):
            self.sleep(2)
            post = self.lookup(key)
            if post:
                return post
        raise EditionError("Uncertain write: inspect all-status WordPress posts before retry or browser fallback")

    def verify_public(self, post, key, media_id, body):
        require(post.get("status") == "publish" and post.get("featured_media") == media_id,
                "Published status/image association not confirmed")
        safe_url(post.get("link", ""), {"sportsmississippi.com"})
        for attempt in range(3):
            response = self.public.get(f"{SITE}/wp-json/wp/v2/posts/{post['id']}",
                                       params={"_edition_check": key}, timeout=(10, 30),
                                       allow_redirects=False)
            if response.status_code == 200:
                visible = response.json()
                if (visible.get("slug") == key and visible.get("status") == "publish"
                        and visible.get("featured_media") == media_id
                        and normalized(BeautifulSoup(body, "html.parser").get_text(" "))
                        == normalized(BeautifulSoup(visible.get("content", {}).get("rendered", ""),
                                                    "html.parser").get_text(" "))):
                    page = self.public.get(post["link"], timeout=(10, 30), allow_redirects=False)
                    media = self.public.get(f"{SITE}/wp-json/wp/v2/media/{media_id}",
                                            timeout=(10, 30), allow_redirects=False)
                    page_text = normalized(BeautifulSoup(page.text, "html.parser").get_text(" "))
                    title_text = normalized(BeautifulSoup(post.get("title", {}).get("rendered", ""),
                                                          "html.parser").get_text(" "))
                    if page.status_code == 200 and media.status_code == 200 and title_text and title_text in page_text:
                        image_url = safe_url(media.json().get("source_url", ""), {"sportsmississippi.com"})
                        image = self.public.get(image_url, timeout=(10, 30), allow_redirects=False)
                        require(image.status_code == 200, "Featured image not publicly accessible")
                        return {"state": "published", "id": post["id"], "url": post["link"],
                                "featured_media": media_id, "edition_id": key}
            if attempt < 2:
                self.sleep(3)
        raise EditionError("Post may already be published; public verification incomplete. Reconcile before fallback")

    def publish(self, data, image, alt):
        key = identity(data)
        title, body = render(data)
        post = self.lookup(key)  # Errors fail closed; no media or post writes.
        if post:
            require(f"<!-- {key} -->" in post.get("content", {}).get("raw", ""),
                    "Slug belongs to a different post; do not overwrite")
            require(post.get("status") in ("draft", "publish"), "Existing edition requires manual reconciliation")
            if post["status"] == "publish":
                existing_body = post["content"]["raw"]
                require(post.get("featured_media", 0) > 0, "Published edition missing image; reconcile")
                return self.verify_public(post, key, post["featured_media"], existing_body)
        else:
            try:
                post = self.api("POST", "posts", json={"title": title, "content": body,
                                "slug": key, "status": "draft", "comment_status": "closed"})
            except EditionError:
                post = self.reconcile(key)
            require(post.get("slug") == key and post.get("status") == "draft"
                    and f"<!-- {key} -->" in post.get("content", {}).get("raw", ""),
                    "Draft creation not confirmed; reconcile before retry")
        # Attach to this same draft; search attached media to recover partial uploads.
        media_id = post.get("featured_media", 0)
        if not media_id:
            media = self.api("GET", "media", params={"parent": post["id"], "search": key,
                             "context": "edit", "per_page": 100})
            require(isinstance(media, list) and len(media) < 100, "Ambiguous media lookup")
            matches = [m for m in media if key in m.get("slug", "")]
            require(len(matches) <= 1, "Multiple edition images; reconcile")
            if matches:
                media_id = matches[0]["id"]
            else:
                try:
                    upload = self.api("POST", "media", params={"post": post["id"], "slug": key},
                        data=image, headers={"Content-Type": "image/png",
                        "Content-Disposition": f'attachment; filename="{key}.png"'})
                    media_id = upload["id"]
                except EditionError:
                    raise EditionError("Media upload uncertain; inspect draft attachments before retry") from None
            self.api("POST", f"media/{media_id}", json={"alt_text": alt, "title": alt, "post": post["id"]})
        categories = self.api("GET", "categories", params={"slug": "sports"})
        payload = {"title": title, "content": body, "featured_media": media_id}
        if categories:
            payload["categories"] = [categories[0]["id"]]
        # Save complete draft before making it public.
        self.api("POST", f"posts/{post['id']}", json=payload)
        ready = self.api("GET", f"posts/{post['id']}", params={"context": "edit"})
        require(ready.get("featured_media") == media_id
                and ready.get("content", {}).get("raw") == body and ready.get("slug") == key,
                "Complete draft verification failed")
        try:
            post = self.api("POST", f"posts/{post['id']}", json={"status": "publish"})
        except EditionError:
            post = self.reconcile(key)
        return self.verify_public(post, key, media_id, body)


def run(data, output, dry_run=False, offline=False, now=None):
    now = now or datetime.now(timezone.utc)
    data = validate(data, now)
    output.mkdir(parents=True, exist_ok=True)
    if not data["games"]:
        return {"state": "skipped_no_verified_games", "edition_id": identity(data)}
    title, body = render(data)
    image, alt = featured_image(data)
    (output / "article.html").write_text(body, encoding="utf-8")
    (output / "featured.png").write_bytes(image)
    (output / "draft.json").write_text(json.dumps({"title": title, "slug": identity(data),
                                      "content": body, "image_alt": alt}), encoding="utf-8")
    require(not offline or dry_run, "Offline mode is permitted only with dry-run")
    public = public_session()
    if not offline:
        verify_sources(data, public)
    if dry_run or not data["publish"]:
        return {"state": "dry_run", "edition_id": identity(data), "sources_checked": not offline}
    require(os.environ.get("WORDPRESS_BASE_URL", "").rstrip("/") == SITE,
            "Managed WordPress destination does not match verified site")
    require(os.environ.get("WORDPRESS_USERNAME") and os.environ.get("WORDPRESS_APP_PASSWORD"),
            "Existing managed WordPress credentials unavailable")
    auth = requests.Session()  # No automatic POST retries, no shared source session.
    auth.auth = (os.environ["WORDPRESS_USERNAME"], os.environ["WORDPRESS_APP_PASSWORD"])
    auth.headers["Accept"] = "application/json"
    return Publisher(auth, public).publish(data, image, alt)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("intake", type=Path)
    parser.add_argument("--output", type=Path, default=Path("edition-output"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    result = {"state": "failed", "fallback": "reconcile_before_browser"}
    try:
        require(args.intake.stat().st_size <= 300_000, "Intake exceeds size limit")
        result = run(json.loads(args.intake.read_text(encoding="utf-8")), args.output,
                     args.dry_run, args.offline)
    except EditionError as error:
        result["reason"] = str(error)
    except Exception:
        # Never echo HTTP response bodies, environment values, or credential-bearing exceptions.
        result["reason"] = "Edition failed; inspect sanitized artifacts and reconcile before retry"
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    return 1 if result["state"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
