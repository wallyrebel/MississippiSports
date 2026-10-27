# Original athletics article depth

The site owner confirmed school/media permission on October 27, 2026 to use
the facts in the existing athletics releases for original coverage. The exact
18 feed hosts are in `AUTHORIZED_ATHLETICS_HOSTS`; this does not authorize new
sources, unrelated publishers, extensive copying, or changes to image rights.

The scraper identifies a story container before pruning it. A page-wide ASP.NET
form must not delete its story. Nested controls, navigation, schedule widgets,
ads and promotional footers are removed; structural forms are unwrapped. The
modern `storyPageContentBody` container is supported. Explicit empty/error
stories remain rejected; there is no entire-page text fallback. Authorized
athletics releases are checked for fuller content even for RSS teasers over
500 characters. Off-list sources retain their previous short-RSS behavior.

The rewriter asks for original source-proportional coverage: results, turning
points, named statistical leaders, relevant context and next events only when
supported. Brief sources remain brief. For sources of at least 120 words, a
coverage floor is 45% of source words, capped at 220 words, with three meaningful
paragraphs (four for sources of 400+ words). These are configurable loss checks,
not a license to pad. A source that cannot support them is held, not inflated.
Repeated long sentences, extended copied passages and numbers absent from source/title are rejected.
Time/play intervals also require their actual source modifier: a goal in the
13th minute does not support a claim about the final 13 minutes, and a two-play
drive does not support saying the first completion came two plays earlier.
The overlap flag catches runs of 28 source words; this is an editorial review
trigger, not a copyright permission threshold or a legal safe harbor.
The numeric check normalizes common AP numbers, ordinals and thousands commas;
it is a narrow guard, not a complete factual or plagiarism checker. RSS also
uses one bounded 800-token source-to-candidate comparison of headline, excerpt
and body. A mismatch, ambiguous assertion, malformed verdict or incomplete
check holds the article; it does not trigger automatic rewriting. This check
is a safeguard, not a factual guarantee. Non-RSS callers are not opted in.
Existing
source holds, volleyball consistency, malformed-response and placeholder gates
remain in force before image, taxonomy and post writes.

Settings: `ARTICLE_MAX_INPUT_CHARS=24000`, `ARTICLE_MAX_OUTPUT_TOKENS=3000`,
`ARTICLE_SUBSTANTIVE_WORDS=120`, `ARTICLE_MINIMUM_FRACTION=0.45`,
`ARTICLE_MINIMUM_CAP=220`. Inputs over budget are held rather than silently
truncated. GPT-6 Luna and reasoning effort `none` remain unchanged. Token use
is logged without prompts or credentials. At the approved $0.10/M input and
$0.50/M output prices, the visible-output cap rises from $0.001 to $0.0015
per generation request; the additional fact-check output cap is $0.0004.
Full-source input and the check's source/candidate input increase actual input
cost proportionally. These are caps, not expected use. No added automatic
generation retry is used.

`tests/test_article_depth.py` exercises six diagnosed school stories using
compact original factual fixtures, form wrappers/controls, longer teasers,
modern containers, rich versus thin coverage, repetition and numeric checks.
The existing offline content checks include this suite. Publisher schedules,
dedupe, source attribution, stable post identities and daily editions do not
change. Existing articles need a separately scoped supported correction route;
the retired October 13 worker is hard-bound to different IDs and must not be
repurposed or re-enabled.
