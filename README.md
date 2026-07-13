# Community Voices

[![tests](https://github.com/BryanZaneee/community-voices/actions/workflows/tests.yml/badge.svg)](https://github.com/BryanZaneee/community-voices/actions/workflows/tests.yml)

A full-stack RAG application that listens to a gaming community and writes a
weekly **Community Voices Document**: what the community talked about, the
standout threads, and what it will talk about next week. Every claim is
grounded in the community's actual posts via retrieval-augmented generation,
with built-in A/B testing of the whole idea.

The default community is **c/games on lemmy.world**, the fediverse's largest
gaming community, chosen deliberately: its API is public by design, so anyone
can run the crawler and the live week-pull with **zero credentials**. (I
would have used Reddit, but scraping it now requires an approved developer
account. Reddit's 2026 Data API gate blocks unauthenticated `.json`/RSS
access, so nobody cloning this repo could reproduce the ingest.) A sidebar
source switcher can wipe and re-ingest the dataset from other open sources:
c/technology, c/asklemmy, or Hacker News (Algolia search API).

![Report tab](docs/report-tab.png)

## Quick start

Two ways to run it:

**1. Hosted demo**: <https://bryanzane.com/com-voices/>. API keys are
already configured server-side, so generation, A/B comparisons, and the
live week pull all work with zero setup.

**2. Local install**: requirements are **Python 3.11+**. Node is *not*
required; the frontend ships pre-built.

```bash
git clone https://github.com/BryanZaneee/community-voices.git
cd community-voices/backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8000
# open http://localhost:8000
```

The repo ships with a pre-ingested corpus (`data/community.sqlite`): a month
of c/games activity as 200 posts, 453 chunks with real voyage-3-large
embeddings, and 5 week windows. Nothing is pre-generated. Every document and
A/B comparison you see is produced live when you click the button, so you
watch the RAG pipeline do its work rather than browse canned output.

Generation needs two free API keys (DeepSeek: platform.deepseek.com, Voyage:
dashboard.voyageai.com). Copy `.env.example` to `.env` in the repo root and
fill in:

| Key | What it unlocks |
|---|---|
| `DEEPSEEK_API_KEY` | Generate weekly documents and run A/B comparisons (retrieval falls back to BM25 keyword search without a Voyage key) |
| `VOYAGE_API_KEY` | Full hybrid retrieval (BM25 + vector, RRF-fused), a fresh trailing-week pull before generating (at most every 12 hours), the "Run now" live pull, and switching ingest sources |
| `ANTHROPIC_API_KEY` (optional) | Adds Claude Opus 4.8 and Claude Sonnet 5 to the sidebar model picker alongside DeepSeek |

Without keys the app still boots: you can browse the embedding map, the
ingested corpus, and the ingestion funnel, and the full test suite runs.

## Using the app

- **Weekly report**: pick a week, click **Generate report**, and watch the
  eight-stage pipeline run live. Download the finished document as `.md` or
  print to PDF.
- **A/B (RAG vs LLM)**: side-by-side documents, scorecard, and verdict (see
  **The A/B test** below). **Generate report** runs the full comparison
  automatically; the A/B tab also has a standalone **Run A/B comparison**
  button (`POST /api/compare`).
- **Embeddings**: the 2-D map of every chunk. Toggle topic clusters vs
  retrieval heat, and click a cluster to inspect its most-retrieved chunks.
- **Ingestion**: the crawl funnel and latest-run numbers. **Run now** pulls
  the trailing 7 days of the current source live (needs a Voyage key).
- **Help**: a plain-English FAQ of the moving parts.
- **Sidebar**: pick the generation model (DeepSeek V4 default; V4 Flash, and
  the Claude models with an Anthropic key) and switch the ingest source,
  which wipes the dataset and re-crawls the chosen community.

## What's inside

```
Lemmy / Hacker News (posts + comments)  FastAPI                   React SPA
        │  crawler (open API,           │                          │
        │  parallel fetches)            │  /api/generate(/stream)  │  Report tab
        ▼                               │  /api/compare            │  A/B tab
  markdown per post ── chunker ──► sqlite-vec vector table         │  Embeddings tab
                          │        + BM25 (in-memory)              │  Ingestion tab
                          ▼             │                          │  Help tab
                    Voyage embeddings   └── retrieval stats,       │
                                            UMAP/PCA + clusters ───┘
```

- **Vector store**: a `vec0` virtual table (sqlite-vec) living in the same
  SQLite file as the relational tables (posts, documents, comparisons,
  retrieval stats). That is "a vectorized database table in a relational
  database," verbatim. Chosen deliberately: cloning the repo *is* getting the
  data, and the schema ports 1:1 to Postgres + pgvector if this were
  multi-writer production.
- **Retrieval**: 6 canonical facet queries ("debates and controversies",
  "questions people are asking", …) run against the selected week's chunks.
  Hybrid mode fuses BM25 and vector KNN with Reciprocal Rank Fusion; every
  retrieved chunk bumps a retrieval counter (the Embeddings tab leaderboard
  and the dot sizes on the embedding map).
- **Generation**: a model registry with DeepSeek V4 (default), DeepSeek V4
  Flash, and, with an Anthropic key, Claude Opus 4.8 and Claude Sonnet 5;
  each generation records latency, token usage, and estimated cost. The
  model emits a structured JSON report
  (headline, topics with discussion share and expandable detail, standout
  threads, confidence-scored predictions); the exported markdown is built from
  it server-side. `GET /api/generate/stream` is the SSE variant that drives
  the UI's live eight-stage pipeline animation.
- **Embedding map**: the stored 2-D projection uses UMAP when `umap-learn` is
  installed (the committed DB ships UMAP coords) and falls back to plain PCA
  otherwise; k-means clusters with TF-IDF term labels color the map.
  Recompute anytime without re-embedding: `.venv/bin/python -m app.rag.pca`.
- **Judging**: blind LLM scoring on every comparison. See **The A/B test**
  below for the rubric and how retrieved chunks are used as ground truth.

Also included: hybrid RRF retrieval, blind LLM-judge scoring, and a live-scrape
button over five week windows of ingested history.

## Report Flow

What happens between clicking **Generate** and reading the report. The eight
stages are: crawl, reduce, embed, retrieve, write, predict, ab, evaluate.

1. **Click**: the Report tab kicks off the fullscreen generation
   animation and opens a Server-Sent Events connection to
   `GET /api/generate/stream` with the selected week and model.
2. **Fresh data first** (crawl / reduce / embed): with a Voyage key, the
   backend runs a live trailing-7-day pull of the current source before
   anything else, so those three stages report that pull's real numbers
   and the model writes from up-to-date data (a failed pull falls back
   to the stored corpus and says so). The pull is skipped when the
   corpus was ingested within the last 12 hours, so back-to-back
   regenerates reuse it.
   Without a Voyage key those three stages instantly replay their real
   numbers from ingest time rather than pretending to redo the work.
3. **Retrieve**: a worker thread runs retrieval. Six fixed facet queries
   ("debates and controversies," "tips and recommendations," …) are each
   searched against *only that week's* chunks using hybrid retrieval,
   BM25 keyword search plus sqlite-vec vector search, fused with
   reciprocal-rank fusion (BM25-only if no Voyage key). Results are
   deduped keeping each chunk's best score, and the top 18 chunks become
   the context.
4. **Write**: the chunks, with their posts' titles, scores, and dates,
   are formatted into a context block and sent to the LLM with a JSON
   schema describing the report (headline, lede, 3-5 topics,
   predictions). Stage events stream back with latency and token counts.
5. **Store**: the model's JSON is rendered to markdown and saved to the
   `documents` table along with everything needed to audit the run:
   the queries, retrieved chunk ids, retrieval mode, latency, and token
   counts. If the model ignored the schema, its raw text is kept and
   rendered as plain markdown.
6. **Predict**: forecasts parsed from the stored report.
7. **A/B**: the same model writes the no-retrieval baseline for the
   comparison.
8. **Evaluate / done**: as soon as both drafts exist the stream emits
   `done` with the RAG document and the report fades in. The blind judge
   keeps scoring in the background; the verdict arrives as a final
   `comparison` event (see **The A/B test** for rubric details). The
   frontend paces the progress bar smoothly (SSE events set the stage
   floor; a ticker eases toward each stage's ceiling, and the two
   LLM-call stages dominate real wall-clock). If generation fails, an
   `error` event surfaces the message and the previously stored report
   stays on screen.

## The A/B test

**RAG vs no-RAG**: the same model writes the document with retrieved context
vs from parametric knowledge alone. This is the core question RAG is supposed
to answer: without it the model can only produce plausible generalities; with
it, it cites real threads with real scores. The A/B tab shows it four ways:
side-by-side documents with grounded claims highlighted and hedged ones
dashed, a claim-composition bar per document, a blind 1-5 rubric scored by an
LLM judge that grades both documents against the RAG run's retrieved source
material (so made-up specifics count against a document, not for it), and
paired run metrics (cost, latency, tokens, verifiable citations) that end in
an honest pros-and-cons verdict. RAG costs more and runs slower, and it is
the only version that says anything true about the week.

Use **Run A/B comparison** on the A/B tab to rerun the comparison for the
selected week without regenerating the report.

## The crawler

`.venv/bin/python -m app.ingest games` (from `backend/`, with `VOYAGE_API_KEY`
in `.env`; nothing else needed). Any Lemmy community works as the positional
argument, and `--source hackernews` crawls Hacker News through the Algolia
search API instead; the in-app source switcher drives the same registry via
`POST /api/ingest/source`. The Lemmy path:

1. **Listing sweep**: paginated requests to Lemmy's open
   `/api/v3/post/list?community_name=games&sort=TopMonth` → ~200 posts.
2. **Comment fetches**: top ~30 posts per trailing 7-day window with ≥5
   comments, fetched in parallel (6 workers), top-level comments only.
3. **Chunk → embed → index**: each post becomes a small markdown doc
   (title, metadata, selftext, top comments), split into ~400-token chunks
   with stable content-hash IDs, embedded in batches of 64, upserted into
   sqlite-vec, then the 2-D projection (UMAP, PCA fallback) and topic
   clusters are recomputed. The run's funnel numbers persist to the meta
   table and feed the Ingestion tab.

Handling "overly large amounts of data": ~200-post cap per month, comment
fetches only where there's real discussion, 12 comments/post, and per-field
truncation. A month lands in the mid-hundreds of chunks (this repo's committed
month: 453). Re-runs are idempotent: content-hashed chunk IDs mean overlapping
windows only embed what's new or edited, and superseded chunks of re-crawled
posts are pruned rather than left stale. The Ingestion tab's **"Run now"**
button runs the same pipeline for the trailing 7 days and the new window
appears in the week selector. Measured on the real month ingest: 200 posts +
115 comment fetches in 6.1 s, chunk + embed + index in 18.9 s.

Because re-runs are idempotent, unattended weekly ingestion is one cron line:

```cron
0 6 * * 1  cd /path/to/community-voices/backend && .venv/bin/python -m app.ingest games --window week
```

## Performance notes

On the committed 453-chunk corpus, hybrid retrieval (BM25 plus sqlite-vec
KNN, RRF-fused) runs in sub-millisecond time. Ingest indexing is dominated by
the Voyage embedding API rather than SQLite.

## Development

The served frontend is a pre-built SPA (`frontend/dist/`, committed on
purpose so evaluators skip Node). To hack on it:

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload   # API on :8000
cd frontend && npm install && npm run dev               # Vite dev server, proxies /api to :8000
cd frontend && npm run build                            # refresh frontend/dist before committing
```

## Tests

```bash
cd backend && .venv/bin/python -m pytest tests -q   # no API keys needed
```

Four layers, run in CI on every push:

- **Unit**: one file per module, fully offline (embeddings faked, LLM calls
  stubbed): chunker (splits, overlap, stable IDs), BM25 (ranking, distance
  transform), vector index (KNN, upserts, dim guards), embeddings, retriever
  (exact RRF math, mode switches, keyless degradation, week filtering), PCA,
  db helpers, ingest (markdown mapping, Lemmy field mapping, idempotency),
  llm (cost math, judge fallback chain), generation (facet retrieval,
  prompts, persistence).
- **API**: every endpoint through FastAPI's TestClient: happy paths, 400/404
  paths, download headers, stats accumulation, the SSE stream's event order,
  the SPA mount, plus the product story end-to-end with every retrieval
  counted exactly once.
- **Real data**: integration tests over the committed store itself, real
  crawled posts and real voyage-3-large vectors, still keyless. Stored
  embeddings double as query vectors, so the suite proves KNN self-retrieval
  (each chunk's own vector finds it at distance ~0), vector-mode and
  week-filtered retrieval, and BM25 ranking against the actual corpus. One
  extra test embeds a live query through the Voyage API when
  `VOYAGE_API_KEY` is present (skipped in CI).
- **Regression**: pins bugs fixed during development (week-boundary
  alignment) plus a golden chunk-ID snapshot protecting the committed vector
  store.

## License

MIT. See [LICENSE](LICENSE).
