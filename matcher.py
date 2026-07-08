"""
Two-stage matcher:
  1. Fast pass: does any known alias appear (exact or near-exact) in the text?
  2. For medium-confidence fuzzy hits, ask the local LLM to confirm relevance
     and produce a one-line company-specific summary -- ONE batched call per
     article covering all ambiguous candidates, not one call each.

High-confidence hits skip the LLM entirely (saves time, and exact string
matches on a specific company name are rarely false positives).
"""

from rapidfuzz import fuzz
from ollama import chat

from config.settings import (OLLAMA_MODEL, FUZZY_HIGH_CONFIDENCE,
                             FUZZY_LOW_CONFIDENCE, CONFIRM_WITH_LLM)

# An ambiguous fuzzy hit is only worth an LLM call if the alias's distinctive
# first word (जोशी, बलेफी, ...) itself appears in the text. Shared sector
# vocabulary (जलविद्युत, हाइड्रोपावर, बैंक) otherwise floods the LLM stage
# with obvious false candidates.
DISTINCTIVE_WORD_CUTOFF = 85

BATCH_CONFIRM_PROMPT = """A Nepali news article mentioned words similar to the
company names listed below (found via fuzzy matching, so some may be false
positives -- a different company with a similar name, or an incidental
mention).

Article text (may be truncated):
---
{text}
---

Companies to check:
{companies}

For EACH company output EXACTLY one line in this format, nothing else:
SYMBOL: yes|no | <one short English sentence on what the article says about
that company, or n/a if not relevant>"""


def find_candidate_matches(article_text: str, aliases: list):
    """
    aliases: list of dicts with symbol, company_en, alias_devanagari
    Returns list of dicts: {symbol, alias, score, stage}
      stage is 'keyword_high' (auto-accept) or 'needs_llm' (ambiguous)
    """
    candidates = []

    for a in aliases:
        alias = a["alias_devanagari"].strip()
        if not alias:
            continue

        if alias in article_text:
            candidates.append({
                "symbol": a["symbol"], "alias": alias,
                "score": 100, "stage": "keyword_high",
            })
            continue

        # score_cutoff lets rapidfuzz bail out early in C++ -- much faster
        # than scoring every alias fully against a long article
        score = fuzz.partial_ratio(alias, article_text,
                                   score_cutoff=FUZZY_LOW_CONFIDENCE)
        if not score:
            continue
        if score >= FUZZY_HIGH_CONFIDENCE:
            candidates.append({
                "symbol": a["symbol"], "alias": alias,
                "score": score, "stage": "keyword_high",
            })
        else:
            words = alias.split()
            if len(words) > 1 and not fuzz.partial_ratio(
                    words[0], article_text,
                    score_cutoff=DISTINCTIVE_WORD_CUTOFF):
                continue  # sector-word collision, not a real candidate
            candidates.append({
                "symbol": a["symbol"], "alias": alias,
                "score": score, "stage": "needs_llm",
            })

    return candidates


def llm_confirm_batch(candidates: list, article_text: str, max_chars: int = 1500):
    """candidates: list of (symbol, company_en). One LLM call for the whole
    article. Returns {symbol: (is_relevant, summary)}."""
    listing = "\n".join(f"- {sym}: {name}" for sym, name in candidates)
    prompt = BATCH_CONFIRM_PROMPT.format(text=article_text[:max_chars],
                                         companies=listing)
    print(f"  [llm] confirming {len(candidates)} ambiguous: "
          + ", ".join(sym for sym, _ in candidates), flush=True)
    try:
        resp = chat(model=OLLAMA_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    # one answer line per company -- cap generation so a
                    # rambling model can't burn minutes per article
                    options={"temperature": 0,
                             "num_predict": 40 * len(candidates) + 40})
        content = resp["message"]["content"]
    except Exception as e:
        return {sym: (False, f"LLM error: {e}") for sym, _ in candidates}

    results = {}
    for line in content.splitlines():
        parts = line.strip().split(":", 1)
        if len(parts) != 2:
            continue
        sym = parts[0].strip().strip("-* ").upper()
        rest = parts[1].strip()
        known = {s for s, _ in candidates}
        if sym not in known:
            continue
        verdict, _, summary = rest.partition("|")
        relevant = "yes" in verdict.lower()
        results[sym] = (relevant, summary.strip() if relevant else "")

    # anything the model didn't answer for: treat as not relevant
    for sym, _ in candidates:
        results.setdefault(sym, (False, ""))
    return results


def match_article(article_text: str, aliases: list):
    """
    Full pipeline for one article. Returns list of dicts ready for db.insert_match:
        {symbol, match_stage, matched_alias, summary}
    """
    candidates = find_candidate_matches(article_text, aliases)
    # dedupe by symbol, keep best-scoring candidate per symbol
    best_by_symbol = {}
    for c in candidates:
        if c["symbol"] not in best_by_symbol or c["score"] > best_by_symbol[c["symbol"]]["score"]:
            best_by_symbol[c["symbol"]] = c

    company_lookup = {a["symbol"]: a["company_en"] for a in aliases}
    results = []

    ambiguous = []
    for symbol, c in best_by_symbol.items():
        if c["stage"] == "keyword_high":
            results.append({
                "symbol": symbol,
                "match_stage": "keyword_high",
                "matched_alias": c["alias"],
                "summary": "",  # can be back-filled with a summarize-only LLM call if desired
            })
        else:
            ambiguous.append((symbol, company_lookup.get(symbol, symbol)))

    if ambiguous and CONFIRM_WITH_LLM:
        verdicts = llm_confirm_batch(ambiguous, article_text)
        for symbol, _ in ambiguous:
            relevant, summary = verdicts[symbol]
            if relevant:
                results.append({
                    "symbol": symbol,
                    "match_stage": "llm_confirmed",
                    "matched_alias": best_by_symbol[symbol]["alias"],
                    "summary": summary,
                })
            # if not relevant, silently drop -- this is exactly the
            # false-positive filtering this stage exists for

    return results
