# Project guide

[Back to the README](../README.md).

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
  retrieval stats): a vector table inside a relational database. Cloning
  the repo *is* getting the data, and the schema ports 1:1 to Postgres +
  pgvector if this ever needs multiple writers.
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
   regenerates reuse it, and it sits behind `ADMIN_TOKEN` like the
   Ingestion tab, so on the hosted instance visitors generate from the
   stored corpus. Without a Voyage key, or without the token, those three
   stages instantly replay their real numbers from ingest time rather
   than pretending to redo the work.
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

Volume control: ~200-post cap per month, comment
fetches only where there's real discussion, 12 comments/post, and per-field
truncation. A month lands in the mid-hundreds of chunks (this repo's committed
month: 453). Re-runs are idempotent: content-hashed chunk IDs mean overlapping
windows only embed what's new or edited, and superseded chunks of re-crawled
posts are pruned rather than left stale. The Ingestion tab's **"Run now"**
button runs the same pipeline for the trailing 7 days and the new window
appears in the week selector. Measured on the real month ingest: 200 posts +
115 comment fetches in 6.1 s, chunk + embed + index in 18.9 s.

### Other sources

Lemmy and Hacker News are built in and need no source credential. Two more
adapters share the same listing sweep, comment fan-out, chunker, and
idempotent upsert, and each is gated on its own credentials:

- **Reddit**: `.venv/bin/python -m app.ingest games --source reddit` crawls
  `/r/<sub>/top.json`. Set `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, and a
  descriptive `REDDIT_USER_AGENT` from a free "script" app at
  <https://www.reddit.com/prefs/apps>; the crawler then authenticates
  app-only against `oauth.reddit.com`. Reddit's Data API gate returns 403 to
  unauthenticated `.json` requests, so credentials are required in practice.
- **X**: `.venv/bin/python -m app.ingest "#gaming -is:retweet" --source x
  --window week` runs X API v2 recent search; the positional argument is the
  query (`X_QUERY` supplies it for the sidebar entry) and replies come from a
  second search on each post's `conversation_id`. Needs `X_BEARER_TOKEN` on
  the Basic tier or above (the free tier has no search), and recent search
  reaches back 7 days only, so `--window month` returns a week.

Both adapters are covered against recorded payload shapes in
`backend/tests/test_ingest_unit.py`. The hosted instance does not exercise
them; it follows c/games on Lemmy.

Because re-runs are idempotent, unattended weekly ingestion is one cron line:

```cron
0 6 * * 1  cd /path/to/community-voices/backend && .venv/bin/python -m app.ingest games --window week
```

## Performance notes

On the committed 453-chunk corpus, hybrid retrieval (BM25 plus sqlite-vec
KNN, RRF-fused) runs in sub-millisecond time. Ingest indexing is dominated by
the Voyage embedding API rather than SQLite.
