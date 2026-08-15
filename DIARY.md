# Bilbo Data — Diary

One line per run. `YYYY-MM-DD HH:MM | routine | produced | pass/fail | note`.
Long reasoning goes in `SHIFT_LOG.md` or `SEO-LOG.md`, never here.

2026-08-15 15:00 | product shift | worker chain CONFIRMED alive after 27d, harvest unwedged + re-enabled, manifest rotation, stale check, project docs | pass | worker died on one unretried 503 with no cron restarter, harvest wedged at the 100MiB cliff then disabled by hand — GITHUB_TOKEN hypothesis was wrong; probe pushed 2 pulses and relayed, full-length chain running; harvest's first cron generation still unconfirmed

2026-08-15 17:30 | seo sweep | measured the counted set: 35 of 923 camera pages carry real data, 888 are address-only stubs; backlog item filed | pass | very likely the real reason the corpus never gained index traction; nothing noindexed (worker revived today, those pages may yet get data); GSC still unverified, 7th run
