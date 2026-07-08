# Monitoring Agents — Realistic Approach Strategy

**Goal:** Scheduled agents that monitor social media, news, blogs, and regulatory sources for economic activity in Nepal, feeding structured events into PostgreSQL for consumption by NEPSE Research OS.

**Hardware constraint:** Everything runs on a LattePanda 3 Delta (Celeron N5105, 8GB RAM, 24/7). Agents run **one at a time**, on schedules or triggered on demand.

---

## 1. Core Architecture Decision

This is a **pipeline with schedules, not a multi-agent system**. Monitoring work is known in advance and repetitive — no runtime planner needed. Save LangGraph-style orchestration for NEPSE Research OS, where dynamic routing actually matters.

**Build:** a single always-on Python service ("agentOS") = FastAPI + APScheduler + a SQLite-backed job queue with **one worker** (guarantees sequential execution).

```
              LattePanda 3 Delta (24/7)
┌────────────────────────────────────────────────────┐
│  agentOS service (FastAPI + APScheduler)           │
│  ├── Scheduler ── cron-style triggers per agent    │
│  ├── Job queue ── SQLite-backed, 1 worker          │◄── Dashboard
│  └── Agents (plain Python jobs):                   │    (trigger runs,
│      • news_agent        (RSS + scrape)            │     view results)
│      • regulatory_agent  (NRB, SEBON, NEPSE)       │
│      • social_agent      (per-platform collectors) │
│      • blog_yt_agent     (blogs + YT transcripts)  │
│      • triage_agent      (local LLM, batch)        │
│      • extraction_agent  (cloud LLM, batch)        │
│      • digest_agent      (daily summary)           │
└──────────────────────┬─────────────────────────────┘
                       ▼
                  PostgreSQL  ◄─── queried by NEPSE Research OS DB Agent
```

Collectors write to a shared `raw_items` table; LLM stages are just another kind of scheduled job processing whatever has accumulated. Collectors (I/O-bound, cheap) and LLM stages (CPU-bound, slow) never overlap.

**Why not Agno / CrewAI / LangGraph here:** every resident framework costs RAM the local LLM needs, and their value (dynamic agent routing) is exactly what a monitoring pipeline doesn't use. APScheduler + a job table gives scheduling, on-demand triggers, run history, and retries in ~200 lines you fully control.

---

## 2. Social Media Access — Platform Reality Check

Primary focus of the project. Ordered by tractability:

| Platform | Access | Verdict |
|---|---|---|
| **Reddit** | Free official API (100 req/min, OAuth) | ✅ v1 — r/NepalStock, r/Nepal_investors, r/Nepal (flair-filtered) |
| **Telegram** | Free API via Telethon (user account joins channels, reads history) | ✅ v1 — NEPSE tip/discussion channels |
| **YouTube** | Free Data API (10k units/day) + transcript extraction | ✅ v1 — Nepali market-analysis channels; transcripts are high-signal |
| **Twitter/X** | Official API from $200/mo; scraping breaks constantly, violates ToS | 💰 Decide with money — pay Basic tier for a filtered follow-list, or skip in v1 |
| **Facebook** | Graph API no longer exposes groups/pages content; scraping needs logged-in sessions, breaks often, gets accounts banned | ⚠️ v2 — painful truth: Nepal's investor chatter lives here, but there's no clean way in. Pragmatic path: curated pages via third-party service (e.g. Bright Data) once pipeline is proven |
| **Viber** | No read API for communities | ❌ Skip despite being huge in Nepal |

**v1 = Reddit + Telegram + YouTube.** Three stable, free, ToS-clean sources — enough to prove the pipeline. Don't let the hardest source (Facebook) block the whole system.

---

## 3. LLM Strategy on 8GB

The N5105 runs a 3–4B quantized model at ~4–8 tok/s — useless interactively, fine for overnight batch. Split work by what each stage needs:

| Stage | Model | Where | Job |
|---|---|---|---|
| **Triage** | Qwen3-4B Q4 (Ollama) | Local | Binary/ternary relevance ("about Nepal economy: yes/no/maybe") + rough topic tag, batched after each collection window |
| **Extraction** | Haiku 4.5 | Cloud | Structured JSON from items that survive triage: event type, tickers, sector, sentiment, figures, date. Cents/day at a few hundred items |
| **Daily digest** | Sonnet | Cloud | One call/day synthesizing events into a briefing — the "escalate only if needed" tier |
| **Dedup** | bge-small embeddings (ONNX, ~130MB) | Local | Same NRB announcement arrives via 8 sources → one event |

**Memory discipline:** Ollama with a resident 4B model takes ~3.5GB. Set `OLLAMA_KEEP_ALIVE=5m` so the model unloads after each batch and collectors never compete with it for RAM.

---

## 4. Data Model — Contract with NEPSE Research OS

Three tables carry the system:

1. **`raw_items`** — one row per collected thing: source, platform, url, author, text, published_at, content hash, embedding. Append-only.
2. **`item_classifications`** — triage + extraction results keyed to raw_items: relevance, topic, sentiment, extracted JSON, producing model.
3. **`economic_events`** — deduplicated, validated events: event_type (rate change, dividend, earnings, IPO, policy, rumor…), tickers[], sector, direction, confidence, source_item_ids[]. **This is the integration point** — the Research OS DB Agent queries this and never needs to know Reddit exists.

Plus a small rollup table: per-ticker per-day sentiment aggregates, joinable straight onto price data.

---

## 5. Daily Schedule (NPT — NEPSE trades Sun–Thu, 11:00–15:00)

| Time | Job |
|---|---|
| 09:30 | News + regulatory sweep → triage → extraction (pre-market briefing ready by 10:45) |
| 12:30 | Social sweep (Reddit/Telegram) — midday chatter during trading |
| 15:30 | Post-close: news + social sweep |
| 20:00 | Deep sweep: YouTube transcripts, blogs, Telegram history catch-up |
| 22:00 | Triage + extraction of everything accumulated, dedup, digest generation |

Any agent is also triggerable on demand from the dashboard (it just enqueues the same job).

**Dashboard:** minimal — one page served by the FastAPI service: agents, last run, items collected, "run now" buttons, latest digest. Half a day of work.

---

## 6. Risks & Mitigations

- **Scraper rot** is the real maintenance cost. RSS/official APIs rot slowly; HTML scrapers rot monthly. Prefer RSS wherever offered; make each collector **fail loudly** (dashboard shows "0 items — selector probably broke"), never silently.
- **Nepali-language content:** much high-signal material (NRB circulars, Setopati, Telegram chatter) is in Devanagari. Verify Qwen's triage quality on real samples early — if weak, route Nepali triage to Haiku too (still cheap).
- **eMMC wear/space:** 64GB fills up. Put Postgres + Ollama models on M.2 SSD if populated. Retention policy: keep extractions forever, raw HTML/full-text 90 days.

---

## 7. Build Order

1. Skeleton service + scheduler + job queue
2. **One collector (Reddit) end-to-end into Postgres** — proves the pipeline
3. Triage agent (local LLM)
4. Extraction agent (cloud LLM)
5. Add sources one at a time: Telegram → YouTube → news RSS → regulatory
6. Dedup + `economic_events` + rollups
7. Dashboard
8. Digest agent
9. v2: Facebook (third-party service), Twitter/X (if budget allows)

Each new source is just a collector module — the agentOS core never changes.
