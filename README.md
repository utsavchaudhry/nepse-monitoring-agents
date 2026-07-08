# NEPSE News Monitoring Agent

Scrapes Nepali financial news sites several times a day, finds articles about
NEPSE-listed companies (matched via curated Nepali/Devanagari company names,
not tickers), stores matches for 7 days in SQLite, and shows them in a small
local dashboard grouped by symbol.

Part of a larger monitoring system for Nepali economic activity — see
[STRATEGY.md](STRATEGY.md) for the overall architecture (social media,
regulatory sources, LLM extraction pipeline, LattePanda deployment).

## How it works

```
scheduler (cron, 4-5x/day)
        │
   pipeline.py ── purge >7-day-old articles
        │
   scraper.py ── 8 sites in config/settings.py, parallel fetch,
        │        already-seen URLs skipped before download
   matcher.py ── exact/near-exact Devanagari alias match (free);
        │        ambiguous fuzzy hits (score 80-94) confirmed by a
        │        local LLM in one batched call per article
     db.py ───── SQLite (data/news_cache.db): articles + symbol matches
        │
 dashboard/app.py ── http://localhost:8050, news grouped by symbol
```

- **Sites**: Merolagani, NepaliPaisa (via its JSON API — the site is
  JS-rendered), Banking Khabar, Urja Khabar, Insurance Khabar, Capital Nepal,
  Corporate Khabar, Online Khabar. CorporateNepal is disabled (Cloudflare
  challenge). All CSS selectors verified against live HTML on 2026-07-08.
- **Aliases**: `data/stock_aliases.csv` — 353 curated rows covering 280
  symbols, including alternate press spellings (चिलिमे जलविद्युत / चिलिमे
  हाइड्रोपावर) and alternate names (नेपाल टेलिकम / नेपाल दूरसञ्चार कम्पनी).
  Edit the CSV, then re-run `python load_aliases.py`.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python dashboard/app.py    # http://localhost:8050 -- works immediately: the
                           # repo ships a data/news_cache.db snapshot
python pipeline.py         # scrape + match to pull in fresh news
python load_aliases.py     # only needed after editing data/stock_aliases.csv
```

When pushing an updated `data/news_cache.db`, blank the article full-text
first (third-party content; the dashboard doesn't use it):

```bash
sqlite3 data/news_cache.db "UPDATE news_articles SET raw_text=''; VACUUM;"
```

Ollama is optional but recommended — it filters false positives from fuzzy
matching:

```bash
ollama pull qwen2.5:7b-instruct   # or qwen2.5:3b-instruct on weak hardware
```

Without it, set `CONFIRM_WITH_LLM = False` in `config/settings.py` and only
exact/near-exact alias hits are kept (faster, slightly lower recall).

## Scheduling (4-5x/day)

```
0 */5 * * * cd /path/to/repo && ./venv/bin/python pipeline.py >> logs/pipeline.log 2>&1
```

Repeat runs are fast: already-scraped URLs are skipped before download, and
NepaliPaisa is filtered to today's/yesterday's news (Nepal time) via its API.

## Config knobs (`config/settings.py`)

| Setting | Default | Meaning |
|---|---|---|
| `RETENTION_DAYS` | 7 | articles older than this are purged each run |
| `MAX_ARTICLES_PER_SITE_PER_RUN` | 25 | cap per site per run |
| `FETCH_WORKERS` | 8 | parallel article downloads |
| `OLLAMA_MODEL` | qwen2.5:7b-instruct | use the 3b model on low-power boxes |
| `CONFIRM_WITH_LLM` | True | False = skip LLM, drop ambiguous fuzzy hits |
| `FUZZY_HIGH/LOW_CONFIDENCE` | 95 / 80 | fuzzy match thresholds |

## Maintenance

- **A site stops producing matches** → its markup probably changed. Run
  `python scraper.py inspect <site_key>` (or `inspect all`) and fix the
  selectors in `config/settings.py`.
- **New company lists on NEPSE** → add a row to `data/stock_aliases.csv`
  (extra rows per symbol are fine for alternate spellings; keep the same
  `symbol`), then `python load_aliases.py`.
- **`generate_aliases.py`** drafts aliases for new symbols from
  `data/stock_list.xlsx` (dictionary + letter-mapping + local LLM for
  leftover proper nouns) — review its output before loading.
