"""
Loads data/stock_aliases.csv (after you've reviewed/corrected it) into SQLite.

Run this again any time you edit the CSV -- it fully replaces the aliases
table each time, so the CSV is always the source of truth.

Usage:
    python load_aliases.py
"""

import pandas as pd
import db
from config.settings import ALIASES_CSV


def main():
    df = pd.read_csv(ALIASES_CSV, encoding="utf-8-sig")
    df["alias_devanagari"] = df["alias_devanagari"].fillna("").astype(str).str.strip()
    df = df[df["alias_devanagari"] != ""]  # skip rows where generation failed

    rows = df.to_dict(orient="records")
    for r in rows:
        r.setdefault("is_primary", 1)

    db.init_db()
    db.replace_all_aliases(rows)
    print(f"Loaded {len(rows)} alias rows into {db.DB_PATH if hasattr(db,'DB_PATH') else 'DB'}")


if __name__ == "__main__":
    main()
