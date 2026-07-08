# NEPSE Monitoring Agents

Scheduled agents that monitor Nepali news sources (and eventually social
media, blogs, and regulatory sites) for economic activity relevant to
NEPSE-listed companies, designed to run 24/7 on a LattePanda 3 Delta and feed
a larger stock-research system.

- **[STRATEGY.md](STRATEGY.md)** — overall architecture: scheduled pipeline
  design, source-by-source social media feasibility for Nepal, local/cloud
  LLM split, data model, and build order.
- **[nepse_news_agent/](nepse_news_agent/)** — the first working agent:
  scrapes ~8 Nepali financial news sites 4-5x/day, matches articles to
  NEPSE symbols via curated Devanagari aliases (exact + fuzzy + local-LLM
  confirmation), stores results in SQLite, and serves a small Dash dashboard
  grouped by symbol. See its [README](nepse_news_agent/README.md) for setup.

## Quick start

```bash
cd nepse_news_agent
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python load_aliases.py     # loads data/stock_aliases.csv into SQLite
python pipeline.py         # scrape + match once
python dashboard/app.py    # http://localhost:8050
```

Ollama (optional, for fuzzy-match confirmation) — set `CONFIRM_WITH_LLM =
False` in `nepse_news_agent/config/settings.py` to run without it.
