"""
Generates a first-draft symbol -> Nepali alias mapping and writes it to
data/stock_aliases.csv for YOU to review.

v2 -- hybrid deterministic + LLM approach. v1 asked the local LLM to render
each full company name and a 7B model produced Hindi-flavoured or hallucinated
output (e.g. Hindi's नुक्ता letters, or invented words). Now:

  1. Generic corporate/financial words (Bank, Hydropower, Finance, ...) come
     from WORD_MAP -- correct Nepali-newspaper orthography, deterministic.
  2. Acronyms (SBI, NIC, IME) are letter-mapped deterministically.
  3. Only leftover proper nouns (Chilime, Balephi, ...) go to the local LLM,
     one word at a time, temperature 0, with a cache so each distinct word is
     transliterated once. Non-Devanagari LLM output is rejected and the roman
     word is kept so your review pass can spot it.
  4. "Limited"/"Ltd" are dropped -- Nepali press never writes them.

The CSV is written incrementally and re-runs resume where they left off
(delete data/stock_aliases.csv to start over). Still a first draft: review
the CSV by hand before `python load_aliases.py`.
"""

import csv
import os
import re
import sys

import pandas as pd
from ollama import chat

from config.settings import STOCK_LIST_XLSX, ALIASES_CSV, OLLAMA_MODEL

# Generic words in their standard Nepali-press spelling (NOT Hindi: Nepali
# writes कम्पनी not कंपनी, डेभलपमेन्ट not डेवलपमेंट, and avoids nukta letters).
# Proper nouns with well-known press spellings are seeded here too.
WORD_MAP = {
    # dropped entirely
    "limited": "", "ltd": "", "the": "",
    # sectors / generic corporate vocabulary
    "bank": "बैंक", "banking": "बैंकिङ", "bikas": "विकास", "bikash": "विकास",
    "development": "विकास", "developer": "डेभलपर", "finance": "फाइनान्स",
    "company": "कम्पनी", "insurance": "इन्स्योरेन्स", "life": "लाइफ",
    "microfinance": "लघुवित्त", "laghubitta": "लघुवित्त",
    "bittiya": "वित्तीय", "sanstha": "संस्था", "micro": "माइक्रो",
    "hydropower": "जलविद्युत", "hydro": "हाइड्रो", "power": "पावर",
    "jal": "जल", "vidhyut": "विद्युत", "vidyut": "विद्युत",
    "jalvidhyut": "जलविद्युत", "jalavidhyut": "जलविद्युत",
    "jalbidhyut": "जलविद्युत", "jalavidyut": "जलविद्युत",
    "energy": "इनर्जी", "urja": "ऊर्जा", "electric": "इलेक्ट्रिक",
    "investment": "इन्भेष्टमेन्ट", "merchant": "मर्चेन्ट",
    "capital": "क्यापिटल", "commercial": "कमर्सियल", "industries": "इन्डस्ट्रिज",
    "industry": "इन्डस्ट्री", "trading": "ट्रेडिङ", "telecom": "टेलिकम",
    "hotel": "होटल", "tourism": "पर्यटन", "cable": "केबल", "car": "कार",
    "airlines": "एयरलाइन्स", "cement": "सिमेन्ट", "mutual": "म्युचुअल",
    "fund": "फन्ड", "general": "जनरल", "group": "ग्रुप",
    # common name words
    "nepal": "नेपाल", "nepali": "नेपाली", "national": "नेशनल",
    "international": "इन्टरनेशनल", "global": "ग्लोबल", "asia": "एशिया",
    "himalayan": "हिमालयन", "himal": "हिमाल", "everest": "एभरेष्ट",
    "agricultural": "कृषि", "citizens": "सिटिजन्स", "standard": "स्ट्यान्डर्ड",
    "chartered": "चार्टर्ड", "prime": "प्राइम", "mega": "मेगा",
    "sunrise": "सनराइज", "united": "युनाइटेड", "union": "युनियन",
    "universal": "युनिभर्सल", "central": "सेन्ट्रल", "progressive": "प्रोग्रेसिभ",
    "reliance": "रिलायन्स", "goodwill": "गुडविल", "best": "बेस्ट",
    "green": "ग्रीन", "greenlife": "ग्रीनलाइफ", "mountain": "माउन्टेन",
    "valley": "भ्याली", "upper": "अपर", "middle": "मिडल", "star": "स्टार",
    "three": "थ्री", "city": "सिटी", "river": "रिभर", "khola": "खोला",
    "mai": "माई", "and": "एण्ड", "of": "अफ", "multipurpose": "मल्टिपर्पस",
    # proper nouns with established press spellings
    "nabil": "नबिल", "machhapuchchhre": "माछापुच्छ्रे", "chilime": "चिलिमे",
    "sanima": "सानिमा", "siddhartha": "सिद्धार्थ", "kumari": "कुमारी",
    "laxmi": "लक्ष्मी", "prabhu": "प्रभु", "soaltee": "सोल्टी",
    "butwal": "बुटवल", "muktinath": "मुक्तिनाथ", "garima": "गरिमा",
    "jyoti": "ज्योति", "pokhara": "पोखरा", "shree": "श्री",
    "manjushree": "मञ्जुश्री", "tamakoshi": "तामाकोशी", "trishuli": "त्रिशूली",
    "karnali": "कर्णाली", "lumbini": "लुम्बिनी", "chandragiri": "चन्द्रगिरी",
    "arun": "अरुण", "modi": "मोदी", "pariyojana": "परियोजना",
    "samriddhi": "समृद्धि", "maya": "माया", "oriental": "ओरियन्टल",
    "shine": "साइन", "resunga": "रेसुङ्गा",
}

# Deterministic Devanagari spellings of English letters, for acronym tokens
# like SBI, NIC, ICFC, NMB.
LETTER_MAP = {
    "A": "ए", "B": "बी", "C": "सी", "D": "डी", "E": "ई", "F": "एफ",
    "G": "जी", "H": "एच", "I": "आई", "J": "जे", "K": "के", "L": "एल",
    "M": "एम", "N": "एन", "O": "ओ", "P": "पी", "Q": "क्यू", "R": "आर",
    "S": "एस", "T": "टी", "U": "यू", "V": "भी", "W": "डब्लू", "X": "एक्स",
    "Y": "वाई", "Z": "जेड",
}

SYSTEM_PROMPT = """You transliterate ONE word at a time from Roman script into
Nepali Devanagari, spelled the way Nepali newspapers write it.

Rules:
- Output ONLY the Devanagari word. No explanation, no quotes, no romanization.
- Use NEPALI orthography, never Hindi. Nepali never uses nukta letters
  (ज़ फ़ ड़ क़), and uses भ where Hindi might use व for English 'v'.
- Most of these words are Nepali place/person names written in Roman script,
  so recover the natural Nepali spelling."""

# few-shot pairs teach the exact task shape
FEWSHOT = [
    ("Balephi", "बलेफी"),
    ("Rasuwagadhi", "रसुवागढी"),
    ("Sahas", "साहस"),
    ("Ngadi", "ङादी"),
    ("Dordi", "दोर्दी"),
    ("Barun", "बरुण"),
]

DEVANAGARI_ONLY = re.compile(r"^[ऀ-ॿ‌‍]+$")


def transliterate_word_llm(word: str) -> str:
    """One word -> Devanagari via local LLM at temperature 0. Returns the
    original roman word if the model output isn't clean Devanagari, so bad
    cases stay visible in the review pass."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for src, dst in FEWSHOT:
        messages.append({"role": "user", "content": src})
        messages.append({"role": "assistant", "content": dst})
    messages.append({"role": "user", "content": word})

    try:
        resp = chat(model=OLLAMA_MODEL, messages=messages,
                    options={"temperature": 0})
        out = resp["message"]["content"].strip().strip('"\'' + "'")
        out = out.splitlines()[0].strip() if out else ""
    except Exception as e:
        print(f"    [warn] LLM failed on '{word}': {e} - is Ollama running?",
              file=sys.stderr)
        return word

    return out if out and DEVANAGARI_ONLY.match(out) else word


def alias_for(company_en: str, cache: dict) -> str:
    """Company name -> draft Devanagari alias. Deterministic where possible,
    LLM (cached per distinct word) for the rest."""
    # drop parentheticals like "(former World Merchant Banking)"
    name = re.sub(r"\(.*?\)", " ", company_en)
    tokens = re.findall(r"[A-Za-z]+|&", name)

    parts = []
    for tok in tokens:
        if tok == "&":
            parts.append("एण्ड")
            continue
        key = tok.lower()
        if key in WORD_MAP:
            parts.append(WORD_MAP[key])
        elif tok.isupper() and len(tok) <= 6:  # acronym: letter-by-letter
            parts.append("".join(LETTER_MAP[c] for c in tok))
        else:
            if key not in cache:
                cache[key] = transliterate_word_llm(tok)
            parts.append(cache[key])

    return " ".join(p for p in parts if p).strip()


def main():
    df = pd.read_excel(STOCK_LIST_XLSX)
    df.columns = [c.strip() for c in df.columns]

    # resume support: skip symbols already in the CSV from a previous run
    done = set()
    if os.path.exists(ALIASES_CSV):
        done = set(pd.read_csv(ALIASES_CSV, encoding="utf-8-sig")["symbol"])
        print(f"Resuming: {len(done)} symbols already in {ALIASES_CSV}")

    fieldnames = ["symbol", "company_en", "sector", "alias_devanagari",
                  "is_primary", "reviewed"]
    write_header = not os.path.exists(ALIASES_CSV)
    cache = {}
    total = len(df)

    with open(ALIASES_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()

        for i, row in df.iterrows():
            symbol = str(row["Symbol"]).strip()
            if symbol in done:
                continue
            company_en = str(row["Company"]).strip()
            sector = str(row["Sector"]).strip()

            alias = alias_for(company_en, cache)
            print(f"[{i + 1}/{total}] {symbol} ({company_en}) -> {alias}")

            writer.writerow({
                "symbol": symbol,
                "company_en": company_en,
                "sector": sector,
                "alias_devanagari": alias,
                "is_primary": 1,
                "reviewed": 0,
            })
            f.flush()  # row-by-row so an interrupted run loses nothing

    print(f"\nDone. Draft aliases are in {ALIASES_CSV}")
    print("IMPORTANT: review the CSV before `python load_aliases.py`:")
    print("  - any roman-script word means the LLM failed on it - fix by hand")
    print("  - add extra rows for companies the press calls by another name")


if __name__ == "__main__":
    main()
