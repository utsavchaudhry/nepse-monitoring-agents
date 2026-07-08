"""
Generic scraper driven by config/settings.py SITES dict.

Run `python scraper.py inspect <site_key>` first for any site you haven't
verified yet -- it dumps the raw listing-page HTML structure around detected
links so you can fix the CSS selectors in settings.py before trusting output.
"""

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from config.settings import SITES, MAX_ARTICLES_PER_SITE_PER_RUN, FETCH_WORKERS

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
TIMEOUT = 15


def fetch(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def get_article_links(site_key: str) -> list:
    cfg = SITES[site_key]
    links = set()
    for listing_url in cfg["listing_urls"]:
        try:
            html = fetch(listing_url)
        except requests.RequestException as e:
            print(f"  [warn] could not fetch listing {listing_url}: {e}", file=sys.stderr)
            continue

        soup = BeautifulSoup(html, "lxml")
        for a in soup.select(cfg["listing_link_selector"]):
            href = a.get("href")
            if not href:
                continue
            full_url = urljoin(cfg["base_url"], href)
            links.add(full_url)

    links = list(links)[:MAX_ARTICLES_PER_SITE_PER_RUN]
    return links


def get_article_content(site_key: str, url: str):
    """Returns (title, body_text) or (None, None) on failure."""
    cfg = SITES[site_key]
    try:
        html = fetch(url)
    except requests.RequestException as e:
        print(f"  [warn] could not fetch article {url}: {e}", file=sys.stderr)
        return None, None

    soup = BeautifulSoup(html, "lxml")

    title_el = soup.select_one(cfg["title_selector"])
    body_el = soup.select_one(cfg["body_selector"])

    title = title_el.get_text(strip=True) if title_el else ""
    body = body_el.get_text(separator=" ", strip=True) if body_el else ""

    if not body:
        # fall back to full page text if selector missed -- better to have
        # noisy text than nothing, matcher will still work on substrings
        body = soup.get_text(separator=" ", strip=True)

    return title, body


def _fetch_nepalipaisa_detail(cfg, news_id, fallback_title):
    """Returns (title, body) for one nepalipaisa article via its JSON API."""
    try:
        resp = requests.get(cfg["detail_api"], params={"newsId": news_id},
                            headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        detail = resp.json().get("result") or {}
    except (requests.RequestException, ValueError) as e:
        print(f"  [warn] nepalipaisa detail {news_id} failed: {e}",
              file=sys.stderr)
        return None, None

    title = (detail.get("newsTitle") or fallback_title or "").strip()
    html = " ".join(d.get("description") or ""
                    for d in detail.get("descriptions") or [])
    body = BeautifulSoup(html, "lxml").get_text(separator=" ", strip=True)
    return title, body


def scrape_nepalipaisa(cfg, skip_url=None):
    """nepalipaisa.com renders its news list with JS, so there are no article
    links in the HTML -- but the backend JSON API the page calls is public.
    Listing: POST list_api; article body: GET detail_api?newsId=N."""
    payload = {
        "dateType": "", "dateFrom": "", "dateTo": "",
        "sectors": [], "companies": [],
        "categoryId": 0, "subCategoryId": 0,
        "pageNo": 1, "itemsPerPage": MAX_ARTICLES_PER_SITE_PER_RUN,
        "pagePerDisplay": 10, "newsType": "", "sectorGroup": "",
    }
    try:
        resp = requests.post(cfg["list_api"], json=payload, headers=HEADERS,
                             timeout=TIMEOUT)
        resp.raise_for_status()
        days = (resp.json().get("result") or {}).get("data") or []
    except (requests.RequestException, ValueError) as e:
        print(f"  [warn] nepalipaisa list API failed: {e}", file=sys.stderr)
        return

    # only today's and yesterday's news (Nepal time). Yesterday is included
    # so a run just after midnight NPT doesn't miss late-evening items; dedup
    # makes the overlap free.
    npt_now = datetime.now(timezone(timedelta(hours=5, minutes=45)))
    fresh = {npt_now.date().isoformat(),
             (npt_now.date() - timedelta(days=1)).isoformat()}

    todo = []  # (news_id, url, fallback_title)
    for day in days:
        if day.get("newsDate") and day["newsDate"] not in fresh:
            continue
        for item in day.get("newsData") or []:
            news_id = item.get("newsId")
            if not news_id:
                continue
            url = cfg["article_url_fmt"].format(news_id=news_id)
            if skip_url and skip_url(url):
                continue
            todo.append((news_id, url, item.get("newsTitle")))
    todo = todo[:MAX_ARTICLES_PER_SITE_PER_RUN]
    print(f"  {len(todo)} new articles")

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        futures = {pool.submit(_fetch_nepalipaisa_detail, cfg, nid, t): url
                   for nid, url, t in todo}
        for fut in as_completed(futures):
            title, body = fut.result()
            if body:
                yield title, futures[fut], body


def scrape_site(site_key: str, skip_url=None):
    """Yields (title, url, body_text) for each article link found.

    skip_url: optional callable(url) -> bool; URLs it returns True for are
    skipped BEFORE their article page is downloaded (pass db.article_exists
    so repeat runs don't re-fetch everything). Downloads run in parallel."""
    cfg = SITES[site_key]
    print(f"Scraping {cfg['name']}...")

    if cfg.get("api") == "nepalipaisa":
        yield from scrape_nepalipaisa(cfg, skip_url)
        return

    links = get_article_links(site_key)
    if skip_url:
        links = [u for u in links if not skip_url(u)]
    print(f"  {len(links)} new candidate links")

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        futures = {pool.submit(get_article_content, site_key, url): url
                   for url in links}
        for fut in as_completed(futures):
            title, body = fut.result()
            if body:
                yield title, futures[fut], body


def inspect(site_key: str):
    """Debug helper: print the raw HTML around where links should be, so you
    can correct the selectors in settings.py."""
    cfg = SITES[site_key]

    if cfg.get("api"):
        print(f"\n=== {cfg['name']} (API-based, no selectors) ===")
        for title, url, body in scrape_site(site_key):
            print(" ", url, "|", title[:60], f"| body {len(body)} chars")
            break
        return

    for listing_url in cfg["listing_urls"]:
        print(f"\n=== {listing_url} ===")
        try:
            html = fetch(listing_url)
        except requests.RequestException as e:
            print(f"  [error] could not fetch: {e}")
            continue
        soup = BeautifulSoup(html, "lxml")
        found = soup.select(cfg["listing_link_selector"])
        print(f"Selector '{cfg['listing_link_selector']}' matched {len(found)} elements")
        for a in found[:5]:
            print(" ", a.get("href"), "|", a.get_text(strip=True)[:60])
        if not found:
            print("  No matches -- open the page source in your browser and")
            print("  update listing_link_selector in config/settings.py")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "inspect":
        print("Usage: python scraper.py inspect <site_key> [<site_key> ...] | all")
        print(f"Available site keys: {list(SITES.keys())}")
        sys.exit(1)
    keys = list(SITES.keys()) if sys.argv[2] == "all" else sys.argv[2:]
    for key in keys:
        if key not in SITES:
            print(f"[error] unknown site key: {key}", file=sys.stderr)
            continue
        inspect(key)
