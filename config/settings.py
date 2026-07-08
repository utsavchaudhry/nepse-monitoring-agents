"""
Central configuration for the NEPSE news agent.

All selectors below were verified against live HTML on 2026-07-08 with
`python scraper.py inspect <site_key>`. Nepali sites change markup
occasionally -- if a site stops producing articles, re-run inspect and fix
its selectors here.
"""

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

DB_PATH = os.path.join(DATA_DIR, "news_cache.db")
STOCK_LIST_XLSX = os.path.join(DATA_DIR, "stock_list.xlsx")
ALIASES_CSV = os.path.join(DATA_DIR, "stock_aliases.csv")

# How long a scraped article + its matches are kept before being purged.
RETENTION_DAYS = 7

# How many listing-page articles to check per site per run (keeps each run fast;
# dedup means older ones are skipped anyway once you've been running a while).
MAX_ARTICLES_PER_SITE_PER_RUN = 25

# Parallel article downloads per site (I/O-bound, safe even on the LattePanda).
FETCH_WORKERS = 8

# --- Local LLM (Ollama) settings -------------------------------------------
# On the LattePanda use "qwen2.5:3b-instruct" -- yes/no confirmation doesn't
# need the 7B model and it's ~4x faster on CPU.
OLLAMA_MODEL = "qwen2.5:7b-instruct"   # confirm/summarize model
OLLAMA_HOST = "http://localhost:11434"

# LLM confirmation of ambiguous fuzzy matches (score 80-94). Set False to
# skip the LLM entirely: ambiguous candidates are then dropped and only
# exact/near-exact alias hits count. Much faster, small recall loss --
# recommended on the LattePanda if runs are still too slow.
CONFIRM_WITH_LLM = True

# Fuzzy match threshold (0-100) for rapidfuzz partial_ratio on aliases.
# Anything >= HIGH_CONFIDENCE is auto-accepted without LLM confirmation.
# Anything between LOW and HIGH triggers an LLM confirmation pass.
# Below LOW is discarded.
FUZZY_HIGH_CONFIDENCE = 95
FUZZY_LOW_CONFIDENCE = 80

# --- Site configs ------------------------------------------------------------
# Each site needs: listing url(s) to check, a selector for article links on
# the listing page, and selectors for title/body on the article page itself.
SITES = {
    "merolagani": {
        "name": "Merolagani",
        "listing_urls": [
            "https://merolagani.com/NewsList.aspx?id=17&type=latest",  # Corporate
            "https://merolagani.com/NewsList.aspx?id=6&type=latest",   # Stock Market
            "https://merolagani.com/NewsList.aspx?id=7&type=latest",   # Company News
        ],
        # Article links on merolagani look like /NewsDetail.aspx?newsID=12345
        "listing_link_selector": "a[href*='NewsDetail.aspx']",
        # .newsTitle marks the article's own headline (plain .media-title is
        # also used for sidebar/related items on the same page)
        "title_selector": "h4.media-title.newsTitle",
        "body_selector": "div.media-content",
        "base_url": "https://merolagani.com",
    },
    "nepalipaisa": {
        "name": "NepaliPaisa",
        # The site is JS-rendered (no article links in the HTML), but its
        # backend JSON API is public. Handled by scrape_nepalipaisa() in
        # scraper.py instead of the generic CSS-selector scraper.
        "api": "nepalipaisa",
        "list_api": "https://nepalipaisa.com/api/GetNewsList",
        "detail_api": "https://nepalipaisa.com/api/GetNews",
        "article_url_fmt": "https://nepalipaisa.com/news-detail/{news_id}",
    },
    "bankingkhabar": {
        "name": "Banking Khabar",
        "listing_urls": ["https://bankingkhabar.com/"],
        # Tailwind theme, article URLs look like /archives/166028
        "listing_link_selector": "a[href*='/archives/']",
        "title_selector": "h1",
        "body_selector": "article.entry-content",
        "base_url": "https://bankingkhabar.com",
    },
    "urjakhabar": {
        "name": "Urja Khabar",
        "listing_urls": ["https://urjakhabar.com/"],
        # article URLs look like /news/0707666422; headlines sit in bare h2/h3
        "listing_link_selector": "h2 a[href*='/news/'], h3 a[href*='/news/']",
        "title_selector": "h1",
        "body_selector": "div.details-content",
        "base_url": "https://urjakhabar.com",
    },
    "insurancekhabar": {
        "name": "Insurance Khabar",
        "listing_urls": ["https://insurancekhabar.com/"],
        "listing_link_selector": "h4.title a, h4.title-big a",
        "title_selector": "h1.entry-title",
        "body_selector": "div.entry-content",
        "base_url": "https://insurancekhabar.com",
    },
    "capitalnepal": {
        "name": "Capital Nepal",
        "listing_urls": ["https://www.capitalnepal.com/"],
        # article URLs look like /detail/82041
        "listing_link_selector": "a[href*='/detail/']",
        # h1s on article pages are footer/contact noise; the headline is a span
        "title_selector": "span.news-big-title",
        "body_selector": "div.editor-box",
        "base_url": "https://www.capitalnepal.com",
    },
    "corporatekhabar": {
        "name": "Corporate Khabar",
        "listing_urls": ["https://corporatekhabar.com/"],
        # href filter drops javascript:void(0) carousel links and externals
        "listing_link_selector": (
            "h3 a[href*='corporatekhabar.com'], h4 a[href*='corporatekhabar.com']"
        ),
        "title_selector": "h1.news_title",
        "body_selector": "div.single-blog-page-area div.col-lg-8",
        "base_url": "https://corporatekhabar.com",
    },
    # "corporatenepal": DISABLED 2026-07-08 -- www.corporatenepal.com sits
    # behind a Cloudflare JS challenge ("Just a moment..."), so plain requests
    # gets a 403. Re-enabling would need cloudscraper or a headless browser;
    # not worth it unless the site turns out to be high-signal.
    "onlinekhabar": {
        "name": "Online Khabar (Business)",
        "listing_urls": ["https://www.onlinekhabar.com/business"],
        # date-based URL filter (/2026/07/...) skips /content/* section pages
        "listing_link_selector": (
            "h2 a[href*='onlinekhabar.com/20'], h3 a[href*='onlinekhabar.com/20']"
        ),
        "title_selector": "h1.entry-title, h1",
        "body_selector": "div.ok18-single-post-content-wrap, div.content",
        "base_url": "https://www.onlinekhabar.com",
    },
    # sebon.gov.np is a regulator site (notices, mostly PDFs) - different
    # shape entirely (not article-style news). Left out of the auto-scraper
    # for now; worth a dedicated small script later if you want circulars.
}
