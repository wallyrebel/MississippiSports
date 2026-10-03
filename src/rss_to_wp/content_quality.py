"""Deterministic RSS publication checks; these are not a general fact checker."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup


def plain_text(content: str) -> str:
    soup = BeautifulSoup(content, "html.parser")
    for element in soup(["script", "style", "nav", "footer", "header", "iframe", "noscript"]):
        element.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def content_problem(content: str) -> Optional[str]:
    """Reject empty content and known extraction/model failure text, by meaning, not length."""
    text = plain_text(content)
    if not text:
        return "empty_content"
    lower = text.lower()
    if re.fullmatch(r"(?:digital )?game day guide\s*:\s*[^!?]+", lower):
        return "link_heading_without_article"
    if re.search(
        r"\b(?:no (?:actual |article |story |substantive |usable )?content (?:is )?(?:available|provided|found)"
        r"|(?:article |story )?content (?:is )?unavailable"
        r"|no (?:actual |usable |substantive )?(?:article|story) (?:text|content)"
        r"|(?:provided|source|input) (?:text|content) (?:only |contains only |consists of only )?(?:contains |consists of )?(?:a )?(?:youtube |website |site )?(?:footer|boilerplate)"
        r"|(?:unable to|cannot|can not) (?:access|extract|rewrite) (?:the )?(?:article|source|content)"
        r"|as an ai(?: language model)?\b)", lower
    ):
        return "content_unavailable"
    platform_phrases = ("contact us creators", "advertise developers", "how youtube works",
                        "test new features", "google llc")
    if sum(phrase in lower for phrase in platform_phrases) >= 3:
        return "platform_boilerplate"
    legal_phrases = ("privacy policy", "terms of service", "terms of use", "all rights reserved",
                     "cookie preferences", "manage consent")
    if sum(phrase in lower for phrase in legal_phrases) >= 3 or "ad blocker detected" in lower:
        return "site_boilerplate"
    if re.search(r"\b(?:just a moment|verify you are human|checking your browser|access denied|"
                 r"enable javascript and cookies to continue|request blocked|page not found|"
                 r"internal server error|service unavailable)\b", lower):
        return "platform_failure"
    if re.fullmatch(r"(?:untitled|n/?a|none|null|no content|coming soon|lorem ipsum[\s\S]*)[.! ]*", lower):
        return "placeholder_content"
    return None


# Exact sources verified during the Oct. 3 audit. These are editorial holds,
# not corrections inferred by a model. Remove only after rechecking the source
# against the official box score; URL query strings must not evade a hold.
_SOURCE_HOLDS = {
    ("bmcusports.com", "/news/2026/10/2/womens-volleyball-volley-toppers-take-down-william-carey-in-four-sets.aspx"):
        "source_conflict_bmcu_match_date_and_tyer_kills",
    ("alcornsports.com", "/news/2026/10/2/womens-volleyball-alcorn-state-drops-three-set-match-to-texas-southern.aspx"):
        "source_conflict_alcorn_set_scores",
}


def source_hold_problem(url: str) -> Optional[str]:
    parsed = urlparse(url or "")
    hostname = (parsed.hostname or "").lower().removeprefix("www.")
    return _SOURCE_HOLDS.get((hostname, parsed.path.rstrip("/").lower()))


_SET_SCORE = r"(?<![\d.])(\d{2})\s*[-–—]\s*(\d{2})(?!\d)"
_SET_LIST = rf"{_SET_SCORE}(?:\s*,\s*{_SET_SCORE}){{2,4}}"


def _set_lists(text: str) -> list[list[tuple[int, int]]]:
    return [[(int(a), int(b)) for a, b in re.findall(_SET_SCORE, match.group())]
            for match in re.finditer(_SET_LIST, text)]


def volleyball_problem(source: str, original_title: str, article: dict) -> Optional[str]:
    """Check current-match summaries and explicitly sourced set scores only.

    A source with a complete set list provides stronger evidence than a sport
    keyword. With no such list, only check an explicit lead's match length.
    Historical games, records, and other sports are outside this narrow check.
    """
    source_text = plain_text(source)
    if not re.search(r"volleyball|volley toppers", original_title + " " + source_text, re.I):
        return None
    source_lists = _set_lists(source_text)
    # Multiple matches in the source are ambiguous; do not infer one match's facts.
    if len(source_lists) > 1:
        return None
    expected_scores = source_lists[0] if source_lists else []
    lead = original_title + " " + source_text[:400]
    count = re.search(r"\bin (three|four|five|3|4|5)[ -]sets?\b", lead, re.I)
    expected_count = len(expected_scores) if expected_scores else (
        {"three": 3, "four": 4, "five": 5, "3": 3, "4": 4, "5": 5}[count[1].lower()]
        if count else None
    )
    body = plain_text(article["body"])
    first_paragraph = BeautifulSoup(article["body"], "html.parser").find("p")
    summary = " ".join((plain_text(article["headline"]), plain_text(article.get("excerpt", "")),
                        first_paragraph.get_text(" ", strip=True) if first_paragraph else body[:400]))
    if expected_count:
        if expected_count > 3 and re.search(r"\bsweep(?:s|ing)?\b|\bswept\b|straight[ -]sets", summary, re.I):
            return "volleyball_sweep_conflicts_with_source"
        for match in re.finditer(r"\bin (three|four|five|3|4|5)[ -]sets?\b", summary, re.I):
            if {"three": 3, "four": 4, "five": 5, "3": 3, "4": 4, "5": 5}[match[1].lower()] != expected_count:
                return "volleyball_set_count_conflicts_with_source"
        for match in re.finditer(r"\b(?:3\s*[-–—]\s*([012])|([012])\s*[-–—]\s*3)\b", summary):
            context = summary[max(0, match.start() - 30):match.end() + 30]
            if re.search(r"\brecord\b|\bimproved to\b|\bfell to\b", context, re.I):
                continue
            if 3 + int(match[1] or match[2]) != expected_count:
                return "volleyball_result_conflicts_with_source"
    if expected_scores:
        output = summary + " " + body
        allowed = {tuple(sorted(pair)) for pair in expected_scores}
        for match in re.finditer(_SET_SCORE, output):
            a, b = match.groups()
            # Season records are not set scores. Check only local set/result
            # language or a score list, so a 25-10 record does not block a recap.
            context = output[max(0, match.start() - 60):match.end() + 60]
            if re.search(r"\brecord\b|\bimproved to\b|\bfell to\b", context, re.I):
                continue
            if not re.search(r"\bset\b|\bsets\b|\bwin\b|\bvictory\b|\bwon\b", context, re.I):
                continue
            # Only volleyball-like point scores, not unrelated records/stat totals.
            if max(int(a), int(b)) >= 25 and tuple(sorted((int(a), int(b)))) not in allowed:
                return "volleyball_set_score_not_in_source"
        expected_order = [tuple(sorted(pair)) for pair in expected_scores]
        for scores in _set_lists(output):
            if [tuple(sorted(pair)) for pair in scores] != expected_order:
                return "volleyball_set_order_conflicts_with_source"
        # A winning result list with a lost second set cannot become a first-two-set lead.
        if sum(a > b for a, b in expected_scores) == 3 and expected_scores[1][0] < expected_scores[1][1]:
            if re.search(r"\b(?:won|winning|took|taking|claimed|captured) (?:the )?(?:first|opening) two sets\b", body, re.I):
                return "volleyball_first_two_sets_conflicts_with_source"
    return None


def source_problem(content: str, title: str) -> Optional[str]:
    problem = content_problem(content)
    if problem:
        return problem
    return volleyball_problem(content, title, {"headline": title, "body": content})


def article_problem(article: object, source: str = "", original_title: str = "") -> Optional[str]:
    """Validate the final payload, including after a requested title override."""
    if not isinstance(article, dict):
        return "invalid_article_shape"
    for field in ("headline", "body", "excerpt"):
        if field == "excerpt" and field not in article:
            continue
        value = article.get(field)
        if not isinstance(value, str):
            return "invalid_article_field"
        if field == "excerpt" and not value.strip():
            continue
        problem = content_problem(value)
        if problem:
            return problem
    tags = article.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        return "invalid_article_tags"
    return volleyball_problem(source, original_title, article)
