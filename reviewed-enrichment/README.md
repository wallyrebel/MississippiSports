# Completed athletics body enrichment — October 27, 2026

The five reviewed body-only updates completed in Actions run
40535625096 at commit c89eed107014cd24bda35fa5d346c110a320536f.
The successful charset-safe authenticated dry-run was 40535236761;
plan SHA256: 993c440a5a78891e4789efdcd45d59656aee072de2cd1e0194d7dad4a89ed05f.

Only 25130, 25134, 25148, 25204 and 25220 were updated. IDs, published
status, creation dates, slugs/URLs, title/excerpt, author, taxonomy,
metadata and image files were verified preserved. Shinn 25216 remains
unchanged. Each enriched article carries a brief transparent update note.

The first apply run 40534454325 stopped before all writes because cached
HTML omitted its HTTP charset. Parsing bytes using the HTML declaration
fixed the comparison; real H1 drift still stops the worker. Both dry-runs
and the first failed preflight wrote zero posts. The completion receipt
records exactly five confirmed updates and independent public verification
also passed.

This one-shot route is retired: its workflow and control file have been
removed, and the completion receipt prevents reapplication. Do not revive
it, change its IDs/digests, or use it as a general post writer. Existing
RSS schedules and daily editions were unchanged.
