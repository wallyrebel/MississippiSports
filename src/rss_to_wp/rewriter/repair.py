"""One bounded repair request for drafts held by the deterministic checks.

Before this module a held draft was discarded and the same story was sent to
the model again on the next scheduled run with an identical prompt, so the same
problem usually came back. A repair request instead returns the draft to the
model once, with the specific problem named.

The repaired draft is not trusted: it must pass every deterministic check
again and then the independent factual comparison. Factual-comparison holds
are never repaired, so a draft cannot be reworded until a model approves it.
"""

from __future__ import annotations

from typing import Optional

REPAIR_CLOSING = (
    "Return the complete corrected article as JSON in the same format. Change only what is "
    "needed to fix this problem. Every number, date, score, record, name and quotation must "
    "appear in ORIGINAL CONTENT; do not calculate, estimate or infer new ones, and do not take "
    "calendar dates from REFERENCE_TIME or SOURCE_PUBLISHED. If the article cannot be corrected "
    "from ORIGINAL CONTENT alone, return null for headline and body."
)


def _listed(values) -> str:
    return ", ".join(f'"{value}"' for value in list(values)[:12])


def repair_feedback(problem: Optional[str], details: Optional[dict] = None) -> Optional[str]:
    """Explain a repairable hold to the model, or return None when nothing can be repaired.

    Missing-content, placeholder and malformed responses are not repairable: the
    model has nothing to report, and asking again only encourages invention.
    """
    details = details or {}
    if problem == "unsupported_numeric_detail":
        specific = (f"These figures appear in your draft but not in ORIGINAL CONTENT or its "
                    f"title: {_listed(details.get('numbers', []))}. Remove each one, or replace "
                    "it with the value the source actually states.")
    elif problem == "unsupported_time_or_play_interval":
        specific = (f"These time or play-count phrases are not in ORIGINAL CONTENT: "
                    f"{_listed(details.get('intervals', []))}. Describe when each play happened "
                    "using only the source's own time and play references.")
    elif problem == "substantive_source_undercovered":
        specific = (f"Your draft has {details.get('body_words', 'too few')} words, but this "
                    f"source supports at least {details.get('minimum_words', 'more')}. Cover more "
                    "of the sourced facts: the result and decisive sequence, named statistical "
                    "leaders, sourced context and the next event when present. Do not pad.")
    elif problem == "substantive_source_needs_paragraphs":
        specific = (f"Your draft has {details.get('paragraphs', 'too few')} paragraphs. Organize "
                    f"the sourced facts into at least {details.get('minimum_paragraphs', 3)} "
                    "meaningful <p> paragraphs.")
    elif problem == "thin_source_overexpanded":
        specific = (f"The source is a brief of {details.get('source_words', 'few')} words and "
                    f"your draft has {details.get('body_words', 'more')}. Cut it to the supported "
                    f"facts in no more than {details.get('maximum_words', 'the source length')} "
                    "words. Remove general commentary.")
    elif problem == "repeated_sentence_padding":
        specific = "Your draft repeats a sentence. Remove the repetition; do not add filler."
    elif problem == "near_verbatim_source_passage":
        specific = (f"A passage of {details.get('matching_words', 'many')} consecutive words "
                    f"matches the source, beginning \"{details.get('passage_starts', '')}\". "
                    "Compose that passage anew in your own sentences and order, keeping names "
                    "and statistics exact.")
    elif problem and problem.startswith("volleyball_"):
        specific = ("Your draft's match result or set scores conflict with the set scores listed "
                    f"in ORIGINAL CONTENT ({problem.replace('_', ' ')}). State the match length "
                    "and every set score exactly as the source lists them, in the same order.")
    else:
        return None
    return ("An automated pre-publication check held your draft. " + specific + " "
            + REPAIR_CLOSING)
