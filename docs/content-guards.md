# RSS publication safeguards (Oct. 3, 2026)

The Oct. 3 empty-content article came from the HailState entry “WATCH: Football vs. Alabama Hype Video.” Its RSS description contains an image and no text. Its article URL redirects to YouTube, whose page text is platform/footer content. Extraction could previously promote whole-page text to article input based on length. The model's valid JSON describing missing content then passed the required-key check and was published.

The college RSS pipeline now rejects empty text, known platform/site boilerplate, access/error pages, missing-content responses, invalid output fields, and incomplete completions. YouTube redirects cannot supply article prose. Extraction prefers actual story containers, including Sidearm's story text container; it no longer treats the entire page body as an article. Rejected scraping falls back to valid RSS text. Valid short updates have no added length threshold and can remain one paragraph. Normal, fenced JSON and fallback model responses share validation, with a final check before any WordPress media, taxonomy or post writes. Models, fallback choices, schedules, category routing, and narrative edition behavior are unchanged.

Recognized valid empty RSS/Atom feeds count as zero work, not errors. Fetch failures, non-feed 200 responses, and malformed empty XML remain errors. Partial XML recovery with entries still logs a parse warning.

## Narrow factual checks and review holds

For unambiguous volleyball source prose, the checks compare current-match summaries with explicit set counts/results and a complete source set list. They reject a four/five-set sweep, altered set scores/order, and a first-two-set claim when the winning source result list includes a lost second set. Other sports and ambiguous multi-match lists are outside this check. Season records and later-paragraph historical sweep references are not current-match set claims.

Two exact source URLs are held before extraction or rewriting because official evidence conflicts with their prose. Holds remain errors and are not marked processed; remove a hold only after editorial rechecking, not just to make a run green. Print URLs, queries and fragments cannot evade the hold.

* [BMCU source](https://bmcusports.com/news/2026/10/2/womens-volleyball-volley-toppers-take-down-william-carey-in-four-sets.aspx) says Thursday and four kills for Teelie Tyer. The [official box score](https://bmcusports.com/sports/womens-volleyball/stats/2026/william-carey-university-miss-/boxscore/5835) records Oct. 2, 2026 (Friday), BMCU winning 25–19, 19–25, 25–15, 25–20, and Tyer with three kills/four digs. Her four points are distinct from kills.
* [Alcorn source](https://alcornsports.com/news/2026/10/2/womens-volleyball-alcorn-state-drops-three-set-match-to-texas-southern.aspx) contains malformed/conflicting set details. The [official Texas Southern box score summary](https://tsusports.com/sports/womens-volleyball/stats/2026/alcorn-state/boxscore/6207) records Oct. 2 and Texas Southern winning 25–19, 25–11, 25–17. The box score's play-by-play also disagrees with the first-set summary, reinforcing the need for review rather than guessing.

These safeguards do not prove every generated fact, athlete statistic or date correct. They do not automatically fetch and reconcile box scores across every college site. Confirmed conflicts are held, not resolved by the model. Public post edits are managed separately.

## Offline verification

Run `PYTHONPATH=src python -m pytest -q`. Tests mock model/HTTP/WordPress operations and cover short updates, empty/image-only entries, footer redirects, final payload writes, response shapes/fenced JSON/fallbacks/truncation, volleyball source contradictions, exact source holds, and valid empty feeds versus real failures. The RSS content offline checks workflow runs these safeguards on relevant pushes and pull requests without invoking the publisher or using publication secrets.

To verify deployment, inspect the next naturally scheduled RSS run and its `head_sha`. Expected diagnostic events are `entry_content_rejected`, `entry_source_held`, `entry_rewrite_rejected`, `rewrite_response_rejected`, and `feed_empty`. A held story or empty video source must not produce media/taxonomy/post writes or a processed dedupe row. Rejection counts can remain nonzero while confirmed source holds are unresolved. Do not dispatch a publication run just to test this patch.
