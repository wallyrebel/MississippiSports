"""Bounded depth and factual-detail checks for original athletics reporting.

These checks catch measurable loss/padding; they are not a general fact checker.
"""
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from bs4 import BeautifulSoup
from rss_to_wp.content_quality import plain_text


def words(text):
    return re.findall(r"\b[\w]+(?:[’'-][\w]+)*\b", plain_text(text))


@dataclass(frozen=True)
class DepthPolicy:
    substantive_words: int = 120
    minimum_fraction: float = 0.45
    minimum_cap: int = 220

    def requirements(self, source):
        count = len(words(source))
        if count < self.substantive_words:
            return 0, 0
        return min(self.minimum_cap, int(count * self.minimum_fraction)), (4 if count >= 400 else 3)

    def instruction(self, source):
        count = len(words(source))
        minimum, paragraphs = self.requirements(source)
        if not minimum:
            return (f"This source has {count} words. It is a brief: preserve the supported facts "
                    "concisely. Do not stretch it into a feature or add generic commentary.")
        return (f"This substantive source has {count} words. Write an original, source-proportional "
                f"report in at least {paragraphs} meaningful paragraphs (normally {minimum}-"
                f"{min(750, max(minimum + 60, int(count * 0.9)))} words). Cover the result and "
                "decisive sequence, named statistical leaders, relevant sourced context and next "
                "event when present. Use a useful heading only when the material warrants it. "
                "This is a factual-coverage target, never permission to pad: return null headline "
                "and body if these requirements cannot be supported. Avoid copying the source's "
                "sentences or following its paragraph order. Never invent quotes, numbers, dates, "
                "records or context; never convert a past source's today into a present-day claim.")


DEFAULT_DEPTH_POLICY = DepthPolicy()


def interval_details(text):
    """Bind time/play counts to their modifier, not just a bag of numbers."""
    text = plain_text(text).casefold()
    for value, name in enumerate(("zero one two three four five six seven eight nine ten "
                                 "eleven twelve thirteen fourteen fifteen sixteen seventeen "
                                 "eighteen nineteen twenty").split()):
        text = re.sub(r"\b" + name + r"\b", str(value), text)
    values=set()
    for modifier, count, unit in re.findall(
            r"\b(final|last|opening|closing|remaining)\s+(\d+)\s+(minutes?|seconds?|plays?)\b", text):
        values.add(("final" if modifier in {"final","last","closing","remaining"} else modifier,
                    count, unit.rstrip("s")))
    for count, unit, direction in re.findall(
            r"\b(\d+)\s+(minutes?|seconds?|plays?)\s+(earlier|later|before|after|remaining|left)\b", text):
        values.add(("final" if direction in {"remaining","left"} else direction, count, unit.rstrip("s")))
    return values


def numeric_details(text):
    text = plain_text(text).casefold()
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    names = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
             "fourteen fifteen sixteen seventeen eighteen nineteen twenty").split()
    for value, name in enumerate(names):
        text = re.sub(r"\b" + name + r"\b", str(value), text)
    for value, name in enumerate(("first", "second", "third", "fourth", "fifth", "sixth",
                                  "seventh", "eighth", "ninth", "tenth"), 1):
        text = re.sub(r"\b" + name + r"\b", str(value), text)
    return set(re.findall(r"(?<!\w)(\d+(?:\.\d+)?)(?:st|nd|rd|th)?(?!\w)", text))


_NUMBER_WORDS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                 "fourteen fifteen sixteen seventeen eighteen nineteen twenty").split()
_ORDINAL_WORDS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
                  "ninth", "tenth")


def _as_written(value, text):
    """Return a normalized number the way the draft spelled it, for logs and repair feedback."""
    forms = [value]
    if value.isdigit():
        number = int(value)
        if number < len(_NUMBER_WORDS):
            forms.append(_NUMBER_WORDS[number])
        if 1 <= number <= len(_ORDINAL_WORDS):
            forms.append(_ORDINAL_WORDS[number - 1])
    lowered = plain_text(text).casefold()
    for form in forms:
        if re.search(r"(?<!\w)" + re.escape(form) + r"(?:st|nd|rd|th)?(?!\w)", lowered):
            return form
    return value


def article_depth_report(article, source, title="", policy=DEFAULT_DEPTH_POLICY):
    """Return ``(problem, details)``; details name what tripped the check.

    The checks are unchanged from ``article_depth_problem``. Details exist so a
    held draft can be audited and so one bounded repair request can say exactly
    what to fix instead of re-rolling the same draft every run.
    """
    body = article.get("body", "")
    text = plain_text(body)
    minimum, paragraphs = policy.requirements(source)
    source_count = len(words(source))
    body_count = len(words(text))
    if not minimum and body_count > max(source_count + 30, int(source_count * 1.4)):
        return "thin_source_overexpanded", {
            "body_words": body_count, "source_words": source_count,
            "maximum_words": max(source_count + 30, int(source_count * 1.4))}
    if minimum and body_count < minimum:
        return "substantive_source_undercovered", {
            "body_words": body_count, "minimum_words": minimum, "source_words": source_count}
    if paragraphs:
        found = len([p for p in BeautifulSoup(body, "html.parser").find_all("p")
                     if p.get_text(" ", strip=True)])
        if found < paragraphs:
            return "substantive_source_needs_paragraphs", {
                "paragraphs": found, "minimum_paragraphs": paragraphs}
    sentences = [re.sub(r"\W+", " ", s).strip().casefold()
                 for s in re.split(r"(?<=[.!?])\s+", text) if len(words(s)) >= 9]
    if len(sentences) != len(set(sentences)):
        repeated = sorted({s for s in sentences if sentences.count(s) > 1})
        return "repeated_sentence_padding", {"repeated": [s[:120] for s in repeated[:3]]}
    # A conservative editorial overlap flag, not a legal safe-harbor formula.
    body_words = words(text)
    overlap = SequenceMatcher(None, [w.casefold() for w in words(source)],
                              [w.casefold() for w in body_words], autojunk=False)
    longest = overlap.find_longest_match()
    if longest.size >= 28:
        return "near_verbatim_source_passage", {
            "matching_words": longest.size,
            "passage_starts": " ".join(body_words[longest.b:longest.b + 12])}
    # A narrow, inspectable numeric guard; numbers must already be in source/title.
    article_text = " ".join((article.get("headline", ""), article.get("excerpt", ""), text))
    intervals = interval_details(article_text) - interval_details(source + " " + title)
    if intervals:
        return "unsupported_time_or_play_interval", {
            "intervals": sorted(" ".join(item) for item in intervals)}
    numbers = numeric_details(article_text) - numeric_details(source + " " + title)
    if numbers:
        return "unsupported_numeric_detail", {
            "numbers": sorted(_as_written(value, article_text) for value in numbers)}
    return None, {}


def article_depth_problem(article, source, title="", policy=DEFAULT_DEPTH_POLICY):
    return article_depth_report(article, source, title, policy)[0]
