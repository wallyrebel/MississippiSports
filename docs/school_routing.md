# School and college archive routing

Every configured feed previously published only to `Sports`. AI-generated tags do not place a post in a WordPress category archive. All 253 feeds now retain `Sports` and explicitly add `College` plus their school; the community-college feeds also add `Juco News`.

The client still accepts the legacy single `category_id`. The RSS runner now resolves all configured category names and sends their IDs together. A category lookup failure stops that article from publishing with incomplete routing. Existing WordPress categories are reused by slug; missing categories are created through the existing client behavior.

## Existing articles and URLs

This change affects newly created posts. It does not edit existing articles, dates, slugs, category parents or menus, and it does not clear the duplicate database. Old posts need a separate, source-based category backfill.

Sports Mississippi uses category-bearing permalinks. Adding categories can affect WordPress's category choice in a permalink. For a backfill, record each existing canonical URL, explicitly retain its current permalink category using the site's supported primary-category mechanism, and test one post before continuing. Verify the URL and archive membership after each update. If an intentional URL change is unavoidable, add an exact redirect to the replacement. Do not bulk-republish old stories or redirect them all to the homepage.

New posts may use a different category component from earlier Sports-only posts. Confirm the site's chosen primary-category behavior with a draft before rolling out the publisher change. Sending multiple category IDs does not itself designate a primary category.

## Other delivery issues corrected

- The per-feed budget now applies after local duplicate detection. A busy feed with five already processed recent items can reach its remaining unseen items. Failed attempts still consume the budget, limiting retries and API use per run.
- Disabled feeds are now honored by the runner.
- Manual workflow inputs use environment variables and a Bash array. A feed name containing spaces or apostrophes stays one argument. Input text is no longer interpolated into the shell program.

## What remains intentional or outside this change

The 48-hour lookback still applies. No-date and older items are skipped. WordPress-level duplicate checks and the source-attribution link remain. The run still tolerates partial errors, so a green Actions run does not mean every feed published successfully. Review `run_complete` and individual error events.

The September 7 run #4825 fetched Ole Miss football, skipped its five selected items because they were already recorded as processed, and published an Ole Miss volleyball story. It also reported two errors: an empty/failed BMCU Archery feed and an MSU video item with no text to rewrite. These are separate from school-category routing.

The hourly RSS configuration covers 18 institutions, not every Mississippi college. Northeast Mississippi has separate box-score code in this repository, but the inspected hourly workflow invokes `run`, not the box-score command. Additional institutions require verified feeds and explicit configuration; they are not automatically discovered.

## Validation

Run `python -m pytest -q` after installing the project dependencies and pytest. Tests cover all configured feeds, school/College/Juco membership, the actual WordPress category payload, legacy calls, failed category lookup, dry-run safety, disabled feeds, and duplicate-heavy feeds under success and failure.

The unit suite uses mocked publishing, images and rewriting and does not contact WordPress or OpenAI. A production dry run may still invoke the rewriter and image fetches; it is not an offline test.
