"""Bounded depth and factual-detail checks for original athletics reporting.

These checks catch measurable loss/padding; they are not a general fact checker.
"""
from dataclasses import dataclass
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


def article_depth_problem(article, source, title="", policy=DEFAULT_DEPTH_POLICY):
    body = article.get("body", "")
    text = plain_text(body)
    minimum, paragraphs = policy.requirements(source)
    source_count = len(words(source))
    if not minimum and len(words(text)) > max(source_count + 30, int(source_count * 1.4)):
        return "thin_source_overexpanded"
    if minimum and len(words(text)) < minimum:
        return "substantive_source_undercovered"
    if paragraphs and len([p for p in BeautifulSoup(body, "html.parser").find_all("p")
                           if p.get_text(" ", strip=True)]) < paragraphs:
        return "substantive_source_needs_paragraphs"
    sentences = [re.sub(r"\W+", " ", s).strip().casefold()
                 for s in re.split(r"(?<=[.!?])\s+", text) if len(words(s)) >= 9]
    if len(sentences) != len(set(sentences)):
        return "repeated_sentence_padding"
    # A narrow, inspectable numeric guard; numbers must already be in source/title.
    article_text = " ".join((article.get("headline", ""), article.get("excerpt", ""), text))
    if numeric_details(article_text) - numeric_details(source + " " + title):
        return "unsupported_numeric_detail"
    return None
