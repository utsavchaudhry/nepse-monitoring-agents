"""
Main entry point -- run this on a schedule (cron / systemd timer), 4-5x/day.

    python pipeline.py

Steps:
  1. Purge articles older than RETENTION_DAYS
  2. For each configured site: get new article links (skip already-scraped)
  3. Match article text against stock aliases (keyword + LLM confirmation)
  4. Store article + matches in SQLite
"""

import sys
import time

import db
from config.settings import SITES
from scraper import scrape_site
from matcher import match_article


def run():
    db.init_db()

    aliases = db.load_aliases()
    if not aliases:
        print("No aliases loaded! Run generate_aliases.py first, review the CSV,")
        print("then load it with: python load_aliases.py")
        sys.exit(1)

    print(f"Loaded {len(aliases)} aliases.")

    print("Purging old data...")
    db.purge_old()

    total_new = 0
    total_matched = 0

    for site_key in SITES:
        site_start = time.time()
        try:
            # skip_url=db.article_exists: already-scraped articles are
            # filtered out BEFORE downloading them, so repeat runs only pay
            # for genuinely new articles
            for title, url, body in scrape_site(site_key, skip_url=db.article_exists):
                article_id = db.insert_article(site_key, url, title, body)
                total_new += 1

                matches = match_article(body, aliases)
                for m in matches:
                    db.insert_match(article_id, m["symbol"], m["match_stage"],
                                     m["matched_alias"], m["summary"])
                    total_matched += 1

                if matches:
                    symbols = ", ".join(m["symbol"] for m in matches)
                    print(f"  MATCH [{symbols}]: {title[:70]}")

        except Exception as e:
            print(f"[error] site {site_key} failed: {e}", file=sys.stderr)
            continue
        print(f"  ({time.time() - site_start:.1f}s)")

    print(f"\nDone. {total_new} new articles scraped, {total_matched} stock matches found.")


if __name__ == "__main__":
    start = time.time()
    run()
    print(f"Took {time.time() - start:.1f}s")
