"""Fail-closed daily edition intake and REST publisher. No source discovery or scheduling.

The researching agent owns semantic verification of games and date evidence. This
worker rechecks fresh source excerpts, restricts dates, and preserves supplied
editorial prose with a reviewed fact ledger. It never writes unsupported narrative.
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
from bs4 import BeautifulSoup, Comment, NavigableString
from PIL import Image, ImageDraw, ImageFont
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SITE = "https://sportsmississippi.com"
CENTRAL = ZoneInfo("America/Chicago")
SOURCE_HOSTS = {
    "maxpreps.com", "alcornsportsms.com", "tippahsports.com",
    "desotocountynews.com", "sportsmississippi.com", "misshsaa.com", "mais.ms",
    "mississippiscoreboard.com", "wdam.com",
}
SPORTS = {
    "football", "volleyball", "basketball", "soccer", "baseball", "softball",
    "cross country", "track and field", "swimming", "tennis", "golf", "wrestling",
    "bowling", "powerlifting", "archery", "esports",
}
LABELS = {"scores": "Scores from last Night", "preview": "Games To Watch"}
STATUSES = "publish,future,draft,pending,private,trash"
FACT_KINDS = {"record", "stakes", "ranking", "history", "result", "schedule", "context"}
ARTICLE_TAGS = {"p", "h2", "h3", "strong", "em", "a", "ul", "ol", "li", "blockquote", "br"}
FACT_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")


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
    if "article" in data:
        validate_article(data)
    if "revision" in data:
        revision = data["revision"]
        require(isinstance(revision, dict) and revision.get("authorized") is True,
                "Revision requires explicit user authorization")
        require("article" in data, "Revision requires a reviewed editorial article")
        require(type(revision.get("post_id")) is int and revision["post_id"] > 0,
                "Revision requires an exact target post ID")
        require(type(revision.get("expected_featured_media")) is int
                and revision["expected_featured_media"] > 0,
                "Revision requires the existing featured media ID")
        require(isinstance(revision.get("id"), str) and FACT_ID.fullmatch(revision["id"]),
                "Invalid revision ID")
        text_field(revision.get("reason"), "revision authorization reason", 500)
        stamp = revision.get("expected_modified_gmt")
        require(isinstance(stamp, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", stamp),
                "Revision requires WordPress expected_modified_gmt snapshot")
        try:
            datetime.fromisoformat(stamp)
        except ValueError:
            raise EditionError("Invalid revision modification timestamp") from None
    return data


def article_facts(data):
    """Game facts get stable input-index IDs; extra context is explicitly supplied."""
    facts = {}
    for index, game in enumerate(data["games"]):
        if game.get("format") == "meet":
            claim = game["name"] + ": " + ", ".join(game["schools"])
            if data["edition"] == "scores":
                claim += "; " + "; ".join(f"{r['school']} team place {r['place']}" for r in game["results"])
        else:
            claim = f"{game['away']} at {game['home']}"
            if data["edition"] == "scores":
                claim += f"; {game['away_score']}-{game['home_score']} Final"
        claim += " " + data["date"]
        if game.get("start_time"):
            claim += " " + game["start_time"]
            claim += " " + datetime.fromisoformat(game["start_time"]).astimezone(CENTRAL).strftime("%-I:%M %p %Z")
        facts[f"game-{index}"] = {"claim": claim, "evidence": game["evidence"], "game_indexes": [index]}
    facts.update({fact["id"]: fact for fact in data.get("article", {}).get("facts", [])})
    return facts


def number_tokens(value):
    # Prose can change score/record punctuation; every claimed numeric token still
    # needs a referenced fact. This is a mechanical guard, not semantic fact checking.
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", html.unescape(str(value)))
    return {str(int(token)) for token in re.findall(r"(?<!\w)\d+(?!\w)", text)}


def validate_article(data):
    article = data["article"]
    require(isinstance(article, dict) and article.get("reviewed") is True,
            "Editorial prose requires explicit source/fact review")
    headline = text_field(article.get("headline"), "editorial headline", 240)
    require("<" not in headline and ">" not in headline, "Editorial headline must be plain text")
    facts = article.get("facts", [])
    require(isinstance(facts, list) and len(facts) <= 300, "Invalid editorial fact ledger")
    seen = set()
    for fact in facts:
        require(isinstance(fact, dict), "Invalid editorial fact")
        fact_id = fact.get("id")
        require(isinstance(fact_id, str) and FACT_ID.fullmatch(fact_id)
                and not fact_id.startswith("game-") and fact_id not in seen, "Invalid or duplicate fact ID")
        seen.add(fact_id)
        require(fact.get("kind") in FACT_KINDS, "Unknown editorial fact kind")
        claim = text_field(fact.get("claim"), "editorial claim", 1200)
        indexes = fact.get("game_indexes")
        require(isinstance(indexes, list) and indexes and len(indexes) <= len(data["games"])
                and all(type(i) is int and 0 <= i < len(data["games"]) for i in indexes),
                "Editorial fact must relate to a covered game")
        require(fact.get("as_of_date") == data["date"], "Editorial fact has stale as_of_date")
        evidence = fact.get("evidence", {})
        require(isinstance(evidence, dict), "Invalid editorial evidence")
        safe_url(evidence.get("url", ""))
        excerpt = text_field(evidence.get("excerpt"), "editorial source excerpt", 2500)
        subjects = evidence.get("subjects")
        require(isinstance(subjects, list) and subjects and len(subjects) <= 20,
                "Editorial evidence requires source subject labels")
        for subject in subjects:
            text_field(subject, "editorial source subject")
            require(normalized(subject) in normalized(excerpt), "Editorial subject absent from evidence")
        require(number_tokens(claim) <= number_tokens(excerpt), "Editorial numeric claim absent from evidence")
        if fact["kind"] == "history":
            try:
                historical_date = date.fromisoformat(fact["fact_date"])
            except (KeyError, ValueError, TypeError):
                raise EditionError("Historical context needs its actual fact_date") from None
            require(historical_date <= date.fromisoformat(data["date"]), "Future historical fact")
            date_excerpt = text_field(evidence.get("date_excerpt"), "historical date excerpt", 200)
            formats = {historical_date.isoformat(), historical_date.strftime("%m/%d/%Y"),
                       historical_date.strftime("%B %-d, %Y"), historical_date.strftime("%m/%d/%y")}
            require(normalized(date_excerpt) in normalized(excerpt)
                    and any(normalized(fmt) in normalized(date_excerpt) for fmt in formats),
                    "Historical event date absent from evidence")
    # Reject unsafe markup/unsupported blocks rather than silently publish partial prose.
    editorial_html(data)


def editorial_html(data):
    article = data["article"]
    source_html = article.get("html")
    require(isinstance(source_html, str) and 150 <= len(source_html) <= 100_000,
            "Editorial HTML must contain a complete article")
    facts = article_facts(data)
    all_used = set()
    def references(value, text):
        require(isinstance(value, (str, list)), "Missing article fact references")
        ids = value.split() if isinstance(value, str) else value
        require(ids and all(isinstance(i, str) and i in facts for i in ids),
                "Article references an unknown or missing fact")
        allowed_numbers = set().union(*(number_tokens(facts[i]["claim"]) for i in ids))
        # Edition date is mechanically verified elsewhere and can appear in any block.
        allowed_numbers |= number_tokens(data["date"])
        require(number_tokens(text) <= allowed_numbers, "Article includes an unsupported numeric claim")
        all_used.update(ids)
    references(article.get("headline_fact_ids"), article["headline"])
    soup = BeautifulSoup(source_html, "html.parser")
    require(all(getattr(node, "name", None) in {"p", "h2", "h3", "ul", "ol", "blockquote"}
                or (isinstance(node, NavigableString) and not node.strip()) for node in soup.contents),
            "Editorial article must use referenced paragraphs or sections")
    paragraphs = 0
    used_links = set()
    approved_links = {fact["evidence"]["url"] for fact in facts.values()}
    approved_links |= {link["url"] for link in data.get("related_links", [])}
    for node in list(soup.descendants):
        if isinstance(node, Comment):
            raise EditionError("Editorial HTML cannot contain hidden comments")
        if isinstance(node, NavigableString):
            if node.strip() and node.parent == soup:
                raise EditionError("Editorial prose must be inside supported HTML blocks")
            continue
        require(node.name in ARTICLE_TAGS, "Unsupported or unsafe editorial HTML tag")
        require(set(node.attrs) <= ({"href", "data-facts"} if node.name == "a" else {"data-facts"}),
                "Unsupported or unsafe editorial HTML attribute")
        if node.name in {"p", "li", "blockquote", "h2", "h3"}:
            references(node.get("data-facts"), node.get_text(" ", strip=True))
            if node.name == "p":
                paragraphs += 1
        if node.name == "a":
            href = node.get("href")
            require(isinstance(href, str) and href in approved_links, "Editorial link lacks verified evidence")
            safe_url(href)
            used_links.add(href)
            node["rel"] = "noopener"
        elif node.name in {"ul", "ol"}:
            require(all(getattr(child, "name", None) == "li" or not str(child).strip()
                        for child in node.contents), "List prose requires referenced list items")
        if "data-facts" in node.attrs:
            del node["data-facts"]
    require(paragraphs >= 3, "Editorial article needs a lede and developed body paragraphs")
    require({f"game-{i}" for i in range(len(data["games"]))} <= all_used,
            "Editorial article must reference every covered game")
    used_fact_urls = {facts[fact_id]["evidence"]["url"] for fact_id in all_used}
    # Footnotes keep source attribution visible without interrupting supplied prose.
    missing_citations = sorted(used_fact_urls - used_links)
    rendered = str(soup)
    if missing_citations:
        citations = "; ".join(f'<a href="{html.escape(url, quote=True)}" rel="noopener">'
                              f'{html.escape(urlparse(url).hostname or "Source")}</a>'
                              for url in missing_citations)
        rendered += f"\n<p><em>Reporting sources: {citations}.</em></p>"
    return rendered


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
    evidence_items = [game["evidence"] for game in data["games"]]
    evidence_items.extend(fact["evidence"] for fact in data.get("article", {}).get("facts", []))
    for evidence in evidence_items:
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
    if "article" in data:
        body = [f"<!-- {identity(data)} -->"]
        if "revision" in data:
            body.append(f"<!-- sportsms-revision:{data['revision']['id']} -->")
        body.append(editorial_html(data))
        body.append(coverage_note(data))
        return data["article"]["headline"], "\n".join(body)
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
    body.append(coverage_note(data))
    if data.get("related_links"):
        body.append("<h2>Related coverage</h2><ul>")
        for link in data["related_links"]:
            body.append(f'<li><a href="{html.escape(link["url"], quote=True)}">{html.escape(link["title"])}</a></li>')
        body.append("</ul>")
    return title, "\n".join(body)


def coverage_note(data):
    checked = ", ".join(s.title() for s in sorted(set(data["checked_sports"])))
    return (f"<p><em>Coverage: {len(data['games'])} verified games. Active sports checked: {html.escape(checked)}. "
            "This is a source-confirmed selection, not a complete statewide scoreboard or schedule. "
            "Unreported results, unconfirmed schedules and unavailable sources are omitted. "
            "Schedules may change.</em></p>")


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
    def __init__(self, session, public, sleeper=time.sleep, recovery=None):
        self.session, self.public, self.sleep = session, public, sleeper
        self.recovery = recovery

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

    def revise(self, data, post, title, body):
        """An explicit, snapshot-guarded update to the same published post only."""
        revision = data["revision"]
        key = identity(data)
        require(revision.get("authorized") is True and post["id"] == revision.get("post_id"),
                "Authorized revision target does not match existing edition")
        require(post.get("status") == "publish" and post.get("slug") == key,
                "Revision requires the identified published edition")
        media_id = post.get("featured_media", 0)
        require(media_id > 0, "Revision must preserve an existing featured image")
        require(media_id == revision.get("expected_featured_media"),
                "Revision featured image differs from authorized snapshot")
        marker = f"<!-- sportsms-revision:{revision['id']} -->"
        def matches(candidate):
            return (candidate.get("content", {}).get("raw") == body
                    and normalized(BeautifulSoup(candidate.get("title", {}).get("raw",
                        candidate.get("title", {}).get("rendered", "")), "html.parser").get_text(" "))
                    == normalized(title) and candidate.get("featured_media") == media_id
                    and candidate.get("status") == "publish" and candidate.get("slug") == key)
        if marker in post.get("content", {}).get("raw", ""):
            require(matches(post), "Revision ID already exists with different content; reconcile")
            result = self.verify_public(post, key, media_id, body)
            return {**result, "operation": "revision_already_applied", "revision_id": revision["id"]}
        # Re-read immediately before mutation so a newer editorial edit isn't lost.
        current = self.api("GET", f"posts/{post['id']}", params={"context": "edit"})
        require(current.get("modified_gmt") == revision.get("expected_modified_gmt")
                and current.get("featured_media") == media_id and current.get("status") == "publish"
                and current.get("slug") == key
                and f"<!-- {key} -->" in current.get("content", {}).get("raw", ""),
                "Revision snapshot changed; read current post and obtain a reviewed revision")
        if self.recovery:
            snapshot = {name: current.get(name) for name in
                        ("id", "slug", "status", "modified_gmt", "title", "content", "featured_media", "link")}
            (self.recovery / "previous-post.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        # Omit status, slug, taxonomy, and media. WordPress updates only title/body
        # and saves its own revision history; the original post remains published.
        uncertain = False
        try:
            self.api("POST", f"posts/{current['id']}", json={"title": title, "content": body})
        except EditionError:
            uncertain = True
        for attempt in range(3 if uncertain else 1):
            if uncertain:
                self.sleep(2)
            updated = self.lookup(key) if uncertain else self.api(
                "GET", f"posts/{current['id']}", params={"context": "edit"})
            require(updated is not None and updated.get("id") == current["id"], "Revision target disappeared; reconcile")
            if matches(updated):
                result = self.verify_public(updated, key, media_id, body)
                return {**result, "operation": "revised", "revision_id": revision["id"]}
            if not uncertain:
                break
        raise EditionError("Revision outcome uncertain; inspect the same post ID before retry or fallback")

    def publish(self, data, image, alt):
        key = identity(data)
        title, body = render(data)
        post = self.lookup(key)  # Errors fail closed; no media or post writes.
        if "revision" in data:
            require(post is not None, "Revision target not found; never create a replacement post")
            validate_article(data)
            return self.revise(data, post, title, body)
        if post:
            require(f"<!-- {key} -->" in post.get("content", {}).get("raw", ""),
                    "Slug belongs to a different post; do not overwrite")
            require(post.get("status") in ("draft", "publish"), "Existing edition requires manual reconciliation")
            if post["status"] == "publish":
                existing_body = post["content"]["raw"]
                require(post.get("featured_media", 0) > 0, "Published edition missing image; reconcile")
                return self.verify_public(post, key, post["featured_media"], existing_body)
            require("article" in data, "A developed editorial article is required before publication")
        else:
            require("article" in data, "A developed editorial article is required before publication")
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
    return Publisher(auth, public, recovery=output).publish(data, image, alt)


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
