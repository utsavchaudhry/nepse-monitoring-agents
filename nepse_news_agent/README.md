# NEPSE News Agent

Scrapes a fixed list of Nepali news sites 4-5x/day, finds articles about
NEPSE-listed companies (matched via Nepali/Devanagari company names, not
tickers), stores matches for 7 days, and shows them in a small local
dashboard grouped by company.

## Why this design

- **SQLite, not Postgres** — this data is disposable (auto-purged weekly),
  so no need for your main `stockmarket` DB or a server process.
- **Two-stage matching** — exact/near-exact Nepali alias match first (fast,
  free); local LLM only steps in to confirm ambiguous fuzzy matches and
  write a one-line summary. Keeps LLM calls to a minimum.
- **Config-driven scrapers** — each site gets its own CSS selectors in
  `config/settings.py` rather than one universal scraper, because Nepali
  news sites don't share a common structure.

## Setup

```bash
cd nepse_news_agent
python -m venv venv
source venv/bin/activate      # or venv\Scripts\activate on Windows
pip install -r requirements.txt
```

Make sure Ollama is running locally with your model pulled:
```bash
ollama pull qwen2.5:7b-instruct
```

## Step 1 — Verify each site's selectors

All selectors in `config/settings.py` were verified against live HTML on
2026-07-08. To re-check them (e.g. if a site stops producing matches):

```bash
python scraper.py inspect all          # or: inspect <site_key> [<site_key> ...]
```

If a selector matches 0 elements, open the site in your browser, view
source (or inspect element) on a headline link, and update
`listing_link_selector` (and `title_selector` / `body_selector` similarly by
checking an actual article page) in `config/settings.py`.

Special cases:
- **nepalipaisa** is JS-rendered, so it's scraped through its public JSON
  API (`scrape_nepalipaisa()` in `scraper.py`) instead of CSS selectors.
- **corporatenepal** is disabled — it sits behind a Cloudflare JS challenge
  that plain `requests` can't pass (would need cloudscraper/headless browser).

## Step 2 — Generate + review company aliases

```bash
python generate_aliases.py
```

This asks your local LLM to guess the Nepali press name for each of your
280 symbols and writes `data/stock_aliases.csv`. **Open this file and check
it carefully** — Nepali company naming in the press is inconsistent, and
this is a first draft, not ground truth. Things to look for:

- Wrong or overly literal transliterations
- Companies referred to by more than one name in practice — add an extra
  row per symbol for each additional common name (copy the row, change
  `alias_devanagari`, keep the same `symbol`)
- Set `reviewed` to `1` once you've checked a row, so you can filter later

Then load the reviewed CSV into SQLite:

```bash
python load_aliases.py
```

Re-run this any time you edit the CSV.

## Step 3 — Run the pipeline

```bash
python pipeline.py
```

This purges anything older than 7 days, scrapes all configured sites,
matches against your aliases, and stores results. Run it once manually
first and check the output before scheduling it.

## Step 4 — Schedule it (4-5x/day)

Example cron entry (every 5 hours):
```
0 */5 * * * cd /path/to/nepse_news_agent && /path/to/venv/bin/python pipeline.py >> logs/pipeline.log 2>&1
```

Or a systemd timer if you prefer that (matches your existing LattePanda
maintenance pattern).

## Step 5 — View the dashboard

```bash
python dashboard/app.py
```

Open http://localhost:8050 — news grouped by symbol, newest first, auto-
refreshes every 5 minutes. Since old articles get purged from the DB, the
dashboard naturally stays current without any extra cleanup logic on its
side.

## Where to run this

- **This laptop** (RTX 4050): faster LLM confirm/summarize step, but not
  always-on.
- **LattePanda**: always-on like your other services, but CPU-only for the
  LLM step — confirmation of ambiguous matches will be slower. Fine for a
  4-5x/day cadence since there's no real-time pressure.

## Known limitations / next steps

- `sebon.gov.np` isn't in the scraper — it's mostly PDF circulars, not
  article-style news, and would need its own small script.
- Selector rot: Nepali news sites change themes occasionally. If a site
  stops producing matches, re-run `scraper.py inspect <site>` first.
- The alias CSV will need ongoing curation as you see real misses —
  treat it like your corporate actions data: trust manual review over
  the automated first pass.
