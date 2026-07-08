"""
SQLite storage for the NEPSE news agent.

Deliberately simple: one file, three tables, no ORM. Aliases are persistent;
articles + matches are ephemeral and purged after RETENTION_DAYS.
"""

import sqlite3
import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from config.settings import DB_PATH, RETENTION_DAYS


SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    company_en TEXT,
    sector TEXT,
    alias_devanagari TEXT NOT NULL,
    is_primary INTEGER DEFAULT 0,
    reviewed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS news_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_site TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    url_hash TEXT UNIQUE NOT NULL,
    title TEXT,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_text TEXT
);

CREATE TABLE IF NOT EXISTS news_stock_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL REFERENCES news_articles(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    match_stage TEXT,       -- 'keyword_high', 'llm_confirmed', 'llm_rejected'
    matched_alias TEXT,
    summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_matches_symbol ON news_stock_matches(symbol);
CREATE INDEX IF NOT EXISTS idx_articles_scraped_at ON news_articles(scraped_at);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def article_exists(url: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM news_articles WHERE url_hash = ?", (url_hash(url),)
        ).fetchone()
        return row is not None


def insert_article(source_site: str, url: str, title: str, raw_text: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO news_articles
               (source_site, url, url_hash, title, raw_text)
               VALUES (?, ?, ?, ?, ?)""",
            (source_site, url, url_hash(url), title, raw_text),
        )
        if cur.lastrowid:
            return cur.lastrowid
        # already existed (race/duplicate) -- fetch its id
        row = conn.execute(
            "SELECT id FROM news_articles WHERE url_hash = ?", (url_hash(url),)
        ).fetchone()
        return row["id"]


def insert_match(article_id: int, symbol: str, match_stage: str,
                  matched_alias: str = "", summary: str = ""):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO news_stock_matches
               (article_id, symbol, match_stage, matched_alias, summary)
               VALUES (?, ?, ?, ?, ?)""",
            (article_id, symbol, match_stage, matched_alias, summary),
        )


def purge_old(days: int = RETENTION_DAYS):
    # scraped_at is stored by SQLite's CURRENT_TIMESTAMP, which is UTC --
    # compare against UTC (naive, to match the stored format), not Nepal time
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM news_articles WHERE scraped_at < ?", (cutoff,)
        )
        # orphaned matches (article deleted) cleaned up via ON DELETE CASCADE


def load_aliases():
    """Returns list of (symbol, company_en, sector, alias_devanagari)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT symbol, company_en, sector, alias_devanagari FROM stock_aliases"
        ).fetchall()
        return [dict(r) for r in rows]


def replace_all_aliases(rows):
    """rows: list of dicts with symbol, company_en, sector, alias_devanagari, is_primary"""
    with get_conn() as conn:
        conn.execute("DELETE FROM stock_aliases")
        conn.executemany(
            """INSERT INTO stock_aliases (symbol, company_en, sector, alias_devanagari, is_primary)
               VALUES (:symbol, :company_en, :sector, :alias_devanagari, :is_primary)""",
            rows,
        )


def get_news_grouped_by_symbol():
    """For the dashboard: recent matches grouped by symbol, newest first."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT m.symbol, a.title, a.url, a.source_site, a.scraped_at, m.summary, m.match_stage
            FROM news_stock_matches m
            JOIN news_articles a ON a.id = m.article_id
            ORDER BY a.scraped_at DESC
            """
        ).fetchall()
        grouped = {}
        for r in rows:
            grouped.setdefault(r["symbol"], []).append(dict(r))
        return grouped
