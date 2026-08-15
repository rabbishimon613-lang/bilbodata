# Bilbo Data — Diary

One line per run. `YYYY-MM-DD HH:MM | routine | produced | pass/fail | note`.
Long reasoning goes in `SHIFT_LOG.md` or `SEO-LOG.md`, never here.

2026-08-15 15:00 | product shift | worker chain CONFIRMED alive after 27d, harvest unwedged + re-enabled, manifest rotation, stale check, project docs | pass | worker died on one unretried 503 with no cron restarter, harvest wedged at the 100MiB cliff then disabled by hand — GITHUB_TOKEN hypothesis was wrong; probe pushed 2 pulses and relayed, full-length chain running; harvest's first cron generation still unconfirmed

2026-08-15 17:30 | seo sweep | measured the counted set: 35 of 923 camera pages carry real data, 888 are address-only stubs; backlog item filed | pass | very likely the real reason the corpus never gained index traction; nothing noindexed (worker revived today, those pages may yet get data); GSC still unverified, 7th run

2026-08-15 19:15 | publisher | nothing shipped, deliberately — the page regeneration would have been a regression | pass | nothing that the site actually serves changed today; regenerated the static surface anyway to refresh the counts and the result was WORSE, so it was reverted: the counts file now holds only today's readings, so every camera page would have lost its cumulative history (one page went 1,283 samples / 4,642 passes down to 178 / 1,030) and the pages carrying real data would have dropped 35 → 30; production verified healthy and unchanged; needs a decision before the next regeneration
