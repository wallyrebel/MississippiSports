# October 13 audited Sports Mississippi corrections

**The six article corrections and Jones media alt are applied. The one-shot
workflow and control file are retired.** The parent approved plan digest
`a8f0a43b3ead5229d5e85fe98a368343d3912fbb1f09e3082eb8ee217db9041c`
from dry-run 38423055605 at commit `bd4953aa648c57be946b8aa09979b2ddd1171c87`.
Apply run 38423916186 confirmed all six post mutations and attempted the single
approved media alt update before a strict derived-media-field check stopped.
Independent read-only reconciliation confirmed the alt update and unchanged file
bytes. No writes were retried.

`corrections/completion-receipt.json` records complete acceptance:
full article text, H1s, excerpts, generated SEO/social metadata, structured article
data, source links, IDs, URLs, dates, media associations and categories passed.
Excluded post 24487 is unchanged. The Jones title/excerpt also passed homepage and
feed checks; the other five posts were absent from those latest-post surfaces.

The attachment's generated description HTML changed only its embedded image alt
from No. 21 to No. 22; this expected derivative change caused the worker's strict
comparison failure. Public media REST and an uncached Jones page render have the
correct No. 22 alt. The normal canonical page initially retained stale image alt
in the WP Rocket Nginx static cache. The parent separately approved the exact
same-title save of post 24510 against fresh raw snapshot
`bcfbf04f9b41c4cea533c1300f31edc7ffdfac793b8f6ed931fdff5e7162f6d6`
and modified timestamp `2026-10-13T15:40:15`, requiring media alt No. 22.
Cache-refresh run 38425980260 succeeded with exactly one post-only save. Its before
snapshot matched that digest, and only normal modified timestamps advanced.
All body/title/excerpt/URL/publication-date/taxonomy/SEO fields and the entire media
record and bytes stayed unchanged. **The ordinary canonical page now renders the
correct No. 22 image alt**, independently verified along with all six articles and
unchanged post 24487. The cache-refresh workflow/control are also retired, and its
worker refuses mutation while the retained receipt exists. No global cache,
plugin or access settings were changed. No blockers remain.

The parent released the Lewisburg ordering hold after its separate account
permission problem. The historic workflow details below explain the completed
bounded route; no new schedule remains and the worker refuses mutation when the
receipt exists.

The fixed manifest contains the parent's exact six title/excerpt/body replacements.
Its public baselines were anonymously reread; originals were fetched in full.
All IDs, published status, dates, URL slugs, authors, categories and images remain.
Only the existing Jones attachment's rank text changes; its file, ID, URL and
ownership are checked. Post 24487 is excluded.

| Post | Correction and verified expansion | Source |
| --- | --- | --- |
| 24483 | Basketball guard, not linebacker; career honors/scoring and season opener. Remove only football tag 179. | [Mississippi State Athletics](https://hailstate.com/news/2026/10/12/mens-basketball-hubbard-secures-all-sec-preseason-media-first-team) |
| 24473 | Mississippi University for Women, not Zachary University; SLIAC individual finishes. Remove only tag 5878. | [The W Athletics](https://owlsathletics.com/news/2026/10/12/zacharys-owl-of-the-week-the-womens-golf-team.aspx) |
| 24451 | Alcorn State, not William Carey; 3–1 October 11 result, sets, records and undisputed player stats. Remove only tag 1869. | [Alcorn Athletics](https://alcornsports.com/news/2026/10/11/womens-volleyball-lady-braves-rally-from-first-set-loss-to-beat-mvsu.aspx) |
| 24445 | Sunday October 11, 3–0, 13–3/3–2; add set scores and undisputed stats. | [Mississippi State Athletics](https://hailstate.com/news/2026/10/11/volleyball-bulldogs-sweep-the-gamecocks) |
| 24510 | Avenger → Avenge; No. 22, not No. 21; working source URL, sets and player stats. Correct existing attachment 24509 alt text only. | [Jones Athletics](https://jcbobcats.com/news/2026/10/12/volleyball-no-22-jones-avenges-early-season-loss-downs-no-25-pearl-river-3-1.aspx), [official box](https://jcbobcats.com/boxscore.aspx?id=10460) |
| 24433 | Expand generic sentence into an attributed October 11 Lowe/Woodruff update. | [Mississippi State Athletics](https://hailstate.com/news/2026/10/11/baseball-statetotheshow-update-october-11) |

The six SEO and social overrides are empty and remain empty. Corrected titles and
excerpts drive generated metadata. No canonical, indexing, redirects, plugin
settings or global taxonomy terms change. Five factual/typo corrections retain
visible notes; the baseball expansion does not invent a factual error.

The copy avoids Alcorn's disputed Jones block totals, Mississippi State's
inconsistent player-name spellings, Jones' inconsistent hitting percentages, and
the baseball source's implausible postseason runs entry. Baseball standings are
attributed to the October 11 report, not described as current October 13 results.

## Managed preflight and review

The new workflow has no schedule and only responds to the single control file.
It uses the existing WordPress secrets inside Actions only. It neither extracts
credentials nor changes roles/access. It shares `sportsms-daily-editions`' serial
lock. Existing hourly RSS does not use that lock; raw snapshots are checked both
before the first write and immediately before each targeted correction.

The initial run checks account capabilities/author ownership first, reads REST
schemas, exhaustively queries the six IDs and one media ID over every supported
status, confirms tags, compares each exact raw/rendered baseline, and fetches fresh
official report bodies and scoreboard anchors. Any 403 or other error stops.
`plan.json`, `review.json`, `preflight.json`, source snapshots and empty
`actions.json` are the review artifacts. The plan digest binds the complete before
snapshots, exact patches, source digests, media-file bytes and worker implementation.

After reviewing a successful dry-run, the parent sets `parent_reviewed: true`,
records that run ID/commit and exact `approved_plan_sha256`, and finally sets
`apply: true`. Fresh preflight must produce the identical plan digest. Mutation
is allowed only on main in the first Actions attempt. It cannot create posts or
change any unlisted field. Uncertain POST responses stop, record the attempted
endpoint and read the same ID; they are never retried automatically.

After writes, the worker checks raw and anonymous public title/body/excerpt,
generated description/DC/Open Graph/Twitter metadata, canonical pages, retained
IDs/dates/media/category fields, and unchanged media bytes. It checks homepage
and feed titles/excerpts when those posts remain present in those surfaces and
records absence without claiming coverage. Structured article data and visible
Jones image alt need the parent's independent rendered-page acceptance check.

On independently confirmed success, commit the completion receipt under
`corrections/completion-receipt.json`, set `apply: false`, and remove the one-shot
workflow. A retained receipt causes the worker to refuse further mutation. If a
run stops after partial success, inspect its `actions.json` and same-ID receipts;
never rerun mutation or overwrite a new edit without a new reviewed baseline.

Local validation:

```sh
python -m pytest tests/test_audited_corrections.py -q
python scripts/correct_audited_posts.py --offline --output /tmp/sports-correction-review
```
