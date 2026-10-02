# Verified high-school editions

The existing hourly `rss_to_wp.yml` publishes college RSS articles to
**https://sportsmississippi.com**. The separate `daily_editions.yml` adds a secure
intake for researched high-school facts, using exactly the existing GitHub-managed
`WORDPRESS_BASE_URL`, `WORDPRESS_USERNAME`, and `WORDPRESS_APP_PASSWORD` secrets.
It does not read/export credentials or schedule new runs. No browser passwords or
saved browser sessions are placed in the repository or Actions.

## Scheduler and secure invocation contract

The dot automation owns both research and the daily **08:00 / 15:00
America/Chicago** schedule, including DST. Do not add a competing GitHub cron.
The repository's college feeds do **not** provide reliable statewide high-school
score/schedule discovery. A successful RSS run does not establish that this new
edition has been researched, uploaded, or published.

1. Research prior-night final results for the morning `scores` edition, and that
   afternoon/evening's upcoming games for `preview`, across active varsity sports.
   Start with MaxPreps, Alcorn Sports MS, Tippah Sports, DeSoto County News, and
   official association/school sources. Verify Mississippi school identity, sport,
   boys/girls division, event date/year, final status or forthcoming schedule, and
   score-to-team mapping against the actual source. Neither a search snippet nor
   a news article's publication date establishes a game's date. Do not infer player
   identities, statistics, venue, or start time. Scheduled games already started
   must not be submitted. Exclude conflicting reports until resolved.
2. Use a verified write-capable GitHub **create_file** / **update_file** connection to write one
   JSON intake on `main` at `editions/inbox/scores-YYYY-MM-DD.json` or
   `editions/inbox/preview-YYYY-MM-DD.json`. The date is the *covered game date*:
   yesterday in Central time for scores, today for preview. A normal authenticated
   connector commit triggers the worker; an authenticated `git push` to main also
   works, as does GitHub's signed-in file editor. No raw PAT, WordPress credential, custom
   dispatch token, or new persistent access is needed. Use `publish: true` only
   for real researched editions. `false` produces artifacts with no WP writes.
   **Access verification:** local Git push succeeded using existing authentication.
   GitHub connector branch/tree/PR writes returned HTTP 403 in this task. Do not
   assume the dot's connector can submit an intake: verify a harmless write on an
   isolated branch in that exact execution environment first. The local GitHub
   browser was also signed out; it is not a verified dispatch route. If the dot
   lacks Git write or a signed-in GitHub UI, it must use its verified WordPress
   browser session and the recovery contract, or request the specific required
   GitHub write access with approval before adding/expanding a connection.
   Each file is public: include only public game facts, minimal verification
   excerpts, source URLs and relevant internal links. Never include private data.
3. Read the resulting `Verified high-school editions` Actions run status and
   `edition-results-<run_id>` artifact `result.json` for that edition. Only
   `state: published` plus the independently opened canonical URL confirms success.
   A successful workflow with `no_intake`, `dry_run` or `skipped_no_verified_games`
   does not mean an article was published. If research found no verified games,
   record the skip and alert/brief the user; do not publish a filler article.
4. On a failed or uncertain run, first read the artifacts and perform an
   **authenticated all-status lookup** by edition slug and marker. Do not submit
   another intake or use the browser while the workflow is still running.
   Uncertain draft/media writes require inspection before retry; a public GET
   alone cannot establish that no draft/private/pending post exists.

For a bounded validation, push `publish: false`, or use the Actions UI's
**Run workflow → dry_run: true**. There is no direct workflow-dispatch operation
exposed by the connected GitHub tool; the connector commit is the supported API
invocation contract, subject to the write-access check above. Intakes committed
to another branch do not publish. Updates to
already published editions return the existing post, rather than overwrite it.

## Intake v1

```json
{
  "version": 1,
  "edition": "scores",
  "date": "YYYY-MM-DD",
  "verified_at": "YYYY-MM-DDTHH:MM:SS-05:00",
  "publish": false,
  "checked_sports": ["football", "volleyball"],
  "games": [
    {
      "sport": "football",
      "division": "boys",
      "state": "MS",
      "level": "high school varsity",
      "date": "YYYY-MM-DD",
      "home": "Full verified Mississippi school name",
      "away": "Full verified Mississippi school name",
      "status": "final",
      "home_score": 0,
      "away_score": 0,
      "evidence": {
        "url": "https://www.maxpreps.com/actual-verified-game-page",
        "excerpt": "A contiguous visible source excerpt identifying date/year, both teams, mapped scores and Final",
        "date_excerpt": "October 1, 2026",
        "home_name": "Exact source's home school label",
        "away_name": "Exact source's away school label"
      }
    }
  ],
  "related_links": [
    {"url": "https://sportsmississippi.com/actual-relevant-story/", "title": "Relevant story title"}
  ]
}
```

This schematic is not a real game or a publishable fixture. For preview, use
`edition: "preview"`, `status: "scheduled"`, and omit both score fields.
`start_time` is optional ISO8601 with explicit Central offset (`-05:00` CDT,
`-06:00` CST), with `evidence.time_excerpt` as a source substring. Omit unverified
time. `game_no` (1–5) separates same-day doubleheaders. For cross-country, track,
swimming and other multi-school events, use `format: "meet"`, `name` and `schools`
(verified participating school names), omit home/away and their scores, and use
`results: [{"school": "Verified school", "place": 1}]` for final team placements.
Meet previews need no `results`. The evidence must identify the meet, schools,
event date/year and final status/placements. Individual athlete results and times
are intentionally excluded until an appropriate verified identity adapter exists.
Here `state: "MS"` means the event includes verified Mississippi schools, not that
the venue necessarily lies inside Mississippi.

Accepted sport values are in `SPORTS` in the publisher. Evidence date forms accept
ISO, MM/DD/YYYY, MM/DD/YY or Month D, YYYY. The fresh visible page text must contain
the complete excerpt, including event date/year, and source aliases for both teams.
The researcher must validate semantic mapping: checking text presence alone does
not prove that a nearby number is the right score or a header is the game's date.
For a source that splits headers/results or requires JS/login, gather another
publicly readable authoritative report with explicit event date and final status.
Don't bypass restrictions. The worker currently fetches public static HTML only.

Sources are restricted to the four requested domains, sportsmississippi.com,
misshsaa.com and mais.ms (including www). Add other reliable official/local hosts
to the checked-in `SOURCE_HOSTS` only after verifying them. A blocked source fails
closed; the researcher can remove the unavailable game with a coverage limitation
or find independent verifiable evidence. Inputs expire after 18 hours and are
rejected when their game date differs from the current Central-time edition.

## Reliability and recovery

- The exact slug and content marker are `sportsms-scores-YYYY-MM-DD` or
  `sportsms-preview-YYYY-MM-DD`. All statuses and marker searches are checked
  before any write. Lookup errors or multiple matches stop publication.
- Actions serializes edition runs and processes only current intakes changed in
  that push, so an afternoon submission does not retry an uncertain morning write.
  Actions can supersede an older pending run; the scheduler must check each run's
  edition-specific result, reconcile first, and resubmit only when safe. The dot task
  must serialize its REST/browser paths too; GitHub cannot lock a separate browser.
- Create an identified draft, upload an original 1600×900 dated typography card,
  attach it to that draft, verify draft content/media, then publish the same ID.
  Public REST content, featured media ID, media/image availability, and canonical
  page HTTP success are checked after publication. No POST is retried blindly.
- A lost create response triggers read-only reconciliation, never another create
  in that run. An uncertain result remains a failure even if the post may have
  succeeded. Artifacts include rendered article HTML, draft JSON, featured PNG and
  sanitized result for browser recovery. Inspect the original run's uncertainty
  before rerunning; do not clear it by treating a single empty public search as
  proof of absence. WordPress has no atomic external idempotency endpoint, so
  deterministic slugs plus serialization/reconciliation are required.
- Source-confirmed games are grouped by sport/division. Coverage is explicitly
  described as incomplete. No player names/statistics or unsupported narrative is
  generated. Internal links must be live Sports Mississippi pages mentioning a
  covered team. Source excerpts are verification artifacts, not reproduced in the
  article. The visual labels are exactly `Scores from last Night` / `Games To Watch`,
  with the covered game date.

## Browser fallback (dot-owned)

Use only the dot's supported authenticated session at
https://sportsmississippi.com/wp-admin/. This worker does not promise that such a
session is available. If the browser is on the login page, the user must establish
that session in that execution environment; local Chrome login is not cloud login.
Do not export cookies or script passwords.

Wait for the original Action to finish, then search all post statuses and drafts
for both the edition slug and marker. If a complete public post exists, verify and
return it. If an identified draft exists, resume that ID, using the saved HTML and
PNG; inspect existing attachments first, set featured image and the deterministic
slug, then publish. If lookup is unavailable/ambiguous or a create is still
uncertain, stop and alert rather than create another post. If absence is established
after reconciliation, browser-create one post with the exact slug/marker and saved
artifacts, verify canonical public page and featured image, then report its URL.
Both paths failing should alert with the edition/date and actionable access/error
reason. Neither path is a guarantee of publication when source/access checks fail.

## Tests

`PYTHONPATH=src pytest tests/test_editions.py` runs bounded offline schema, source,
rendering, DST, duplicate, partial-write, media and public-verification scenarios.
No live posts or new WordPress access are needed. For offline artifacts:
`PYTHONPATH=src python -m rss_to_wp.editions.publisher <fixture> --dry-run --offline`.
Offline checks never count as live evidence verification or credential validation.
