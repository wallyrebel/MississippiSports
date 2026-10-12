# One explicitly reviewed Tupelo news article

**Retired after completion.** The article is public as post 24460 with attachment
24461. `news/publication-receipt.json` retains the independently verified result.
`reviewed_news.yml` has been removed, the intake is `publish: false`, and the
worker refuses mutation mode while the receipt exists. No new schedule remains.

The user approved the single-news route and the Alden Wade article. This bounded
transport accepts only the fixed headline, topic slug, original portrait digest,
reviewed prose and two exact reporting source identities in `news.publisher`.
It never discovers news, rewrites text, uses stock imagery, creates credentials,
creates taxonomy, or adds schedules. Existing RSS and game-edition code and
workflows remain unchanged.

Only changes to `news/inbox/alden-wade-2026-10-11.json` on `main` start the new
workflow. The same existing GitHub-managed WordPress credentials are injected
only into the worker, never retrieved by the operator. Its concurrency group
shares the existing edition lock. Do not concurrently operate the article in a
browser or submit another intake while its run is active. Automatic mutation
reruns are refused.

Start with `publish: false`. Offline checks do not authenticate or verify fresh
sources. The managed preflight reads edit-context identity/capabilities, derives
all supported post/media statuses from REST schemas, exhaustively paginates each
slug/name/source/event/original-filename query, compares candidate image originals
by SHA-256 and pixels, and checks the existing Prep Sports category. Errors,
changing/incomplete pagination, conflicting event posts, duplicate original
portraits or inaccessible image originals fail closed. Inspect its exact Action,
`result.json`, `reconciliation.json`, `review.json` and empty `actions.json`.

Only after final parent review, record that preflight's run ID/commit and exact
article/image digests in `preflight`, set `parent_reviewed: true`, and set
`publish: true`. Fresh sources and all identity checks run again. The worker
creates one owned draft, uploads or reuses the supplied unchanged portrait,
confirms alt/parent, sets article SEO fields, checks the unchanged draft snapshot,
and publishes the same post ID. Existing independent articles are never edited.
Any earlier draft requires its explicit `recovery_post_id`; a missing recovery
post never causes creation of a replacement. Lost responses trigger read-only
same-event/post reconciliation and failure, never a blind second POST.

The supplied coach quote is attributed to Ty Hardin with publisher-supplied
verbatim provenance. No independently found social post is claimed. The school
statement was visually inspected in both original user-supplied statement images.
The police release does not identify Wade; WTVA's coroner attribution supplies
that bridge. Fresh checks use the exact police post within its saved RSS feed
and the full WTVA report. The article excludes age, class year, driving status,
cause, statistics and service details.

Success requires independent public REST and canonical-page checks of the exact
body, headline/H1, image association, original bytes/pixels, source links,
description, SEO title, self-canonical and indexability. Save the exact run and
sanitized actions. Once independently confirmed, retire `reviewed_news.yml` and
disable this article's mutation entry point; do not leave automatic publication
of unrelated news enabled.

Local checks from the repository root:

```sh
PYTHONPATH=src python -m pytest tests/test_news.py tests/test_editions.py -q
PYTHONPATH=src python -m rss_to_wp.news.publisher news/inbox/alden-wade-2026-10-11.json --offline --output /tmp/tupelo-review
```

## Final portrait verification

The theme initially rendered the portrait with `object-fit: cover` in a wide
frame. The supported WordPress core `media/24461/sideload` endpoint accepted the
same original JPEG with `image_size: original` and `convert_format: false`;
`media/24461/finalize` completed that same attachment. The post's seven paragraphs,
headline, slug, taxonomy and SEO remained unchanged. Fixed CSS limited to
`#post-24460 .cm-featured-image` now displays the whole portrait proportionally.
Chrome verified both natural and displayed dimensions as 765×906 with
`object-fit: contain`, and the complete actual image was visually inspected.

WordPress subsequently applies normal JPEG recompression even on that restored
file. The parent's completion instructions explicitly accepted minor compression
differences instead of repeated/destructive uploads. Public dimensions and
appearance are preserved; average channel difference is 0.786 on a 0–255 scale
(PSNR 45.89 dB). The final read-only receipt accurately distinguishes the approved
original digest from the served JPEG/pixel digests. Do not claim final served
bytes are identical to the Library original or modify global/plugin settings to
change this behavior. There were no AI edits, new attachment IDs, credential or
permission changes, or changes to any other post or schedule.
