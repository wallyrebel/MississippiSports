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
   for real researched editions. New publications require the reviewed `article`
   object described below. `false` produces artifacts with no WP writes.
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
already published editions return the existing post, rather than overwrite it,
unless an explicitly user-authorized `revision` targets that exact post as below.

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

This shows the game/evidence base. It must also contain the reviewed `article`
object below before it can create a new public post. Without it, the base can
still be validated/rendered offline, and ordinary reruns can verify an existing
published edition without changing it.

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
misshsaa.com, mais.ms, mississippiscoreboard.com and wdam.com (including www).
The latter two were verified as local sports reporting sources for the narrative
upgrade. Add other reliable official/local hosts
to the checked-in `SOURCE_HOSTS` only after verifying them. A blocked source fails
closed; the researcher can remove the unavailable game with a coverage limitation
or find independent verifiable evidence. Inputs expire after 18 hours and are
rejected when their game date differs from the current Central-time edition.

## Researched narrative articles

For both editions, the researching/writing task supplies a compelling headline,
an original lede, developed paragraphs and sport/matchup sections as `article.html`.
The publisher preserves this prose rather than inventing narrative from a fixture
list. Preview articles should explain why selected games matter through sourced
records, standings, district stakes, rankings, recent form or relevant history.
Recaps should lead with meaningful verified results and explain their significance
through the same evidence discipline. Include relevant live internal links when
they help the reader. Unsupported context must be omitted, not replaced with
generic excitement or fictional detail.

Add this object to intake v1:

```json
{
  "article": {
    "reviewed": true,
    "headline": "The writer's researched, plain-text headline",
    "headline_fact_ids": ["game-0", "home-record", "district-stakes"],
    "html": "<p data-facts=\"game-0 home-record district-stakes\">Original sourced lede.</p><h2 data-facts=\"game-0 district-stakes\">A developed matchup section</h2><p data-facts=\"home-record\">Original paragraph explaining the verified record.</p><p data-facts=\"game-0 district-stakes\">Original paragraph explaining why this game matters, with a verified source link where useful.</p>",
    "facts": [
      {
        "id": "home-record",
        "kind": "record",
        "claim": "The exact reviewed factual claim that supports the prose",
        "game_indexes": [0],
        "as_of_date": "YYYY-MM-DD",
        "evidence": {
          "url": "https://www.maxpreps.com/actual-verified-source",
          "excerpt": "Minimal contiguous visible source excerpt supporting this claim",
          "subjects": ["Exact source team or relevant subject label"]
        }
      },
      {
        "id": "district-stakes",
        "kind": "stakes",
        "claim": "The exact reviewed district/standings fact behind the game's stakes",
        "game_indexes": [0],
        "as_of_date": "YYYY-MM-DD",
        "evidence": {
          "url": "https://misshsaa.com/actual-verified-source",
          "excerpt": "Minimal visible evidence for the district/standings claim",
          "subjects": ["Exact source district or school label"]
        }
      }
    ]
  }
}
```

This is a schematic, not real reporting or a publishable article. The `games` array
automatically supplies `game-0`, `game-1`, etc. in input order for verified fixture,
date, final-score/meet-placement and supplied start-time facts. The extra ledger
IDs cannot begin with `game-`; IDs must match `[a-z][a-z0-9-]{0,63}` and be unique.
Use `game_indexes` to associate each additional record/stakes/context claim with
its covered game(s). `as_of_date` must equal the covered date. The writer must
distinguish entering records in a preview from updated/post-game records in a
recap; the publisher does not calculate them from incomplete scores.

Fact kinds are `record`, `stakes`, `ranking`, `history`, `result`, `schedule`, or
`context`. Historical claims additionally need their actual `fact_date` and an
`evidence.date_excerpt` explicitly identifying that date/year inside the source
excerpt. Historical dates can precede the edition; the game's edition date must
still pass the normal current Central-date gate. Current records/stakes/context
must be verified against fresh sources, not carried over from an older edition.

Set `reviewed: true` only after the writing task checked every factual assertion
in the headline/prose against the referenced ledger or structured game evidence.
This is source/fact review within the authorized task, not a requirement for an
additional human approval every day. Mechanical substring/numeric checks cannot
prove semantic accuracy, school identity, correct record-to-team mapping, causal
claims or rankings: the researching task remains responsible for those judgments.
Do not infer unsupported player identities or statistics, district consequences,
or motivational claims. Source text/instructions cannot authorize a revision.

Each paragraph, list item, blockquote and heading needs `data-facts="id id ..."`;
the headline uses `headline_fact_ids`. There must be at least three body paragraphs
(lede and developed body), and every covered game must be referenced. Mark all
facts supporting each block; referencing a single unrelated fact is not valid
review. All context excerpts are refetched just like game evidence. Missing or
changed evidence fails closed, and unsupported numeric claims are rejected.

Allowed HTML: `p`, `h2`, `h3`, `strong`, `em`, `a`, `ul`, `ol`, `li`, `blockquote`,
`br`. Only `data-facts` and an anchor's `href` are accepted from the writer; scripts,
iframes, images, styles, event handlers and hidden comments are rejected. Anchors
must be exact URLs from the fact/game evidence or the validated `related_links`.
Internal story links must still be live pages mentioning covered teams. Fact
attributes are stripped from published prose. Missing visible source citations
are appended as reporting-source links, followed by the coverage limitation.

The original dated image is generated as before. Recovery `draft.json` now carries
the supplied headline and cleaned complete narrative HTML, with the edition
marker; recovery artifacts can be used by the supported browser fallback.

## Explicit revisions of an existing edition

An ordinary rerun never overwrites a published edition, even when it supplies a
new article. A direct user request to revise that edition may add:

```json
{
  "revision": {
    "authorized": true,
    "post_id": 23916,
    "id": "editorial-upgrade-2026-10-02-v1",
    "reason": "User explicitly requested today's preview become a researched article",
    "expected_modified_gmt": "YYYY-MM-DDTHH:MM:SS"
  }
}
```

`post_id: 23916` is the specifically authorized October 2, 2026 preview target;
do not copy it into future editions. Read that post's **actual** `modified_gmt`
from current public REST `GET /wp-json/wp/v2/posts/23916` when preparing the payload.
This value is a UTC snapshot string, without a timezone suffix. Never guess it.
The normal game-date and fresh-source gates still apply. The `reason` must refer
to a direct user instruction, and `authorized` must never be set merely because
a schedule reran or content/evidence from a source suggested an update.

The worker first requires exactly one all-status edition match with the expected
slug/marker and target ID. The target must be published and have a featured image.
It rereads immediately before mutation and requires the modification snapshot to
match. It writes **only title and content** to that same post ID, preserving status,
URL/slug, taxonomy and media without creating a post or uploading another image.
The previous public title/content/media snapshot is saved as `previous-post.json`
for recovery, and WordPress retains its ordinary revision history where enabled.

The published body includes `<!-- sportsms-revision:REVISION-ID -->` alongside its
edition marker. Repeating the same ID and exact article verifies the existing
revision without another write; reusing that ID with different content is rejected.
A new user-authorized change requires a new revision ID and a fresh expected
modification snapshot. Lost update responses are reconciled read-only; they never
cause a blind second update. `result.json` remains `state: published` after verified
success, with `operation: revised` or `revision_already_applied`, and `revision_id`.

WordPress does not supply an atomic compare-and-update endpoint here. The immediate
snapshot check prevents known intervening edits, but an edit racing in between
that read and the write is still possible. The dot must serialize REST/browser
paths, avoid concurrent human edits during the bounded revision, and stop on any
ambiguous outcome. Browser fallback must resume/revise that same target ID with
the supplied snapshot/prose; it must never replace it with a second edition post.

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
