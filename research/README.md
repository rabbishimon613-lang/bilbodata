# Research Library — how an entry is built

Two files per document. Nothing else.

## 1. The raw markdown

`research/<slug>.md` — the full research report. This is the artifact. It is downloadable
from the top of the rendered page via the **↓ Raw Markdown** button, unmodified.

Start from `TEMPLATE.md`. Rules that make the visualization work:

- `## N. Section title` — numbered H2s become the numbered section markers and the
  right-hand Contents rail. An **unnumbered H2 placed before the first numbered one is
  treated as the deck line and is hidden** (it already appears in the page header).
- Tables render as instrument tables. Cells that are pure numbers/values render green;
  cells reading `None`, `not stated`, `not publicly specified` render red. Absence is
  a finding, so say it in those exact words.
- `>` blockquotes become the green-rule pull quotes — use for exact vendor wording.
- Bold the load-bearing nouns. The renderer leans on that.

## 2. The metadata

`research/index.json` — one object per doc, in `docs[]`:

| Field | Purpose |
|---|---|
| `id` | `DOC-001`. Shown on the archive card and the doc header. |
| `title` | Full title with the em-dash subtitle. |
| `category` | Groups the archive and fills the filter pills. |
| `date`, `read` | Card meta line. |
| `file` | Path to the markdown. |
| `blurb` | 2–3 lines on the archive card. Say what the doc concludes, not what it covers. |
| `stats[]` | The tile row. `{k, v, sub, tone}` — tone is `""`, `good`, `warn` or `bad`. **Use six** — they lay out 3×2 on desktop, 2×3 on phone, with no orphan tile. |
| `headline` | The callout under the header. `{title, tone, body}`. Title in caps, `HEADLINE FINDING — <the claim>`. |

## Rendering

`research.html?doc=DOC-001` renders any entry. No build step, no dependencies —
the markdown renderer is inline and the page is static.

Archive index lives in the Library page, Research Library section (`library.html#research`).
