"""
price_lookup.py — fetch raw and PSA prices for a Pokemon card.

Usage:
    python price_lookup.py "Charizard ex" "125/197"
    python price_lookup.py "Charizard" "4/102" --set "Base"

Sources (free tiers):
  - Pokemon TCG API (api.pokemontcg.io) — no key required, includes TCGPlayer
    market prices when available.
  - PokemonPriceTracker API (pokemonpricetracker.com) — free tier 100 credits/day.
    Requires a free API key. Provides PSA 9 / PSA 10 prices and population data.

Output: prints a one-line CSV row you can paste into the Card Decisions tab,
plus a human-readable breakdown.

Setup:
  1. pip install requests
  2. (Optional but recommended) Get a free key at https://www.pokemonpricetracker.com
     and either set env var POKEMONPRICETRACKER_API_KEY or paste it below.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from typing import Any, Optional

try:
    import requests
except ImportError:
    sys.stderr.write("Missing dependency. Run: pip install requests\n")
    sys.exit(1)

# --- Config -------------------------------------------------------------
PPT_KEY = os.environ.get("POKEMONPRICETRACKER_API_KEY", "")  # paste here if you prefer
TCG_API_BASE = "https://api.pokemontcg.io/v2"
PPT_API_BASE = "https://www.pokemonpricetracker.com/api/v1"
TIMEOUT = 15

# --- Helpers ------------------------------------------------------------

def search_tcg_card(name: str, number: Optional[str], set_hint: Optional[str]) -> Optional[dict]:
    """Search Pokemon TCG API and return the best-matching card dict."""
    q_parts = [f'name:"{name}"']
    if number:
        # Card numbers like "4/102" — Pokemon TCG API stores just "4"
        n = number.split("/")[0].strip()
        q_parts.append(f"number:{n}")
    if set_hint:
        q_parts.append(f'set.name:"{set_hint}"')
    q = " ".join(q_parts)
    params = {"q": q, "pageSize": 10, "orderBy": "-set.releaseDate"}
    r = requests.get(f"{TCG_API_BASE}/cards", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json().get("data", [])
    if not data:
        return None
    # If the user specified a set, prefer exact match; else prefer most recent
    if set_hint:
        for c in data:
            if (c.get("set") or {}).get("name", "").lower() == set_hint.lower():
                return c
    return data[0]


def extract_tcg_market_price(card: dict) -> Optional[float]:
    """Pull the most representative TCGPlayer market price from a TCG API card record."""
    prices = ((card.get("tcgplayer") or {}).get("prices") or {})
    if not prices:
        return None
    # Prefer holofoil > 1stEditionHolofoil > reverseHolofoil > normal
    for variant in ("holofoil", "1stEditionHolofoil", "reverseHolofoil", "normal", "unlimitedHolofoil"):
        v = prices.get(variant) or {}
        if v.get("market"):
            return float(v["market"])
    # Fall back to any market price found
    for v in prices.values():
        if isinstance(v, dict) and v.get("market"):
            return float(v["market"])
    return None


def fetch_ppt_prices(name: str, number: Optional[str], set_hint: Optional[str]) -> Optional[dict]:
    """Query PokemonPriceTracker for graded price history. Returns
    {'psa10': float, 'psa9': float, 'psa8': float, 'last5_psa10': [...], 'last5_psa9': [...]}.
    Schema is best-effort — adjust to the exact shape the free tier returns when you receive a real response."""
    if not PPT_KEY:
        return None
    headers = {"Authorization": f"Bearer {PPT_KEY}"}
    params: dict[str, Any] = {"name": name, "limit": 5}
    if number:
        params["number"] = number.split("/")[0].strip()
    if set_hint:
        params["set"] = set_hint
    try:
        r = requests.get(f"{PPT_API_BASE}/prices", headers=headers, params=params, timeout=TIMEOUT)
        if r.status_code == 401:
            sys.stderr.write("PokemonPriceTracker: invalid API key\n")
            return None
        if r.status_code == 429:
            sys.stderr.write("PokemonPriceTracker: rate limited (free tier = 100/day)\n")
            return None
        r.raise_for_status()
        body = r.json()
    except (requests.RequestException, ValueError) as e:
        sys.stderr.write(f"PokemonPriceTracker request failed: {e}\n")
        return None

    # Normalize: their schema may use either 'data' (single card) or list. Below is
    # defensive — print raw shape and let user adapt if the free tier differs.
    if isinstance(body, dict) and "data" in body and isinstance(body["data"], list) and body["data"]:
        record = body["data"][0]
    elif isinstance(body, list) and body:
        record = body[0]
    else:
        record = body if isinstance(body, dict) else {}

    out = {"psa10": None, "psa9": None, "psa8": None, "last5_psa10": [], "last5_psa9": [], "raw_record": record}

    # Try a few common key layouts
    psa = record.get("psaPrices") or record.get("psa") or record.get("graded") or {}
    if isinstance(psa, dict):
        if psa.get("10") or psa.get("psa10"):
            out["psa10"] = float(psa.get("10") or psa.get("psa10"))
        if psa.get("9") or psa.get("psa9"):
            out["psa9"] = float(psa.get("9") or psa.get("psa9"))
        if psa.get("8") or psa.get("psa8"):
            out["psa8"] = float(psa.get("8") or psa.get("psa8"))

    # Try to surface last-5 sales arrays if present
    sales = record.get("recentSales") or record.get("sales") or []
    if isinstance(sales, list):
        for s in sales:
            grade = str(s.get("grade") or s.get("psa") or "").strip()
            price = s.get("price") or s.get("soldPrice")
            if price is None:
                continue
            try:
                price = float(price)
            except (TypeError, ValueError):
                continue
            if grade in ("10", "PSA 10"):
                out["last5_psa10"].append(price)
            elif grade in ("9", "PSA 9"):
                out["last5_psa9"].append(price)

    out["last5_psa10"] = out["last5_psa10"][:5]
    out["last5_psa9"] = out["last5_psa9"][:5]
    if out["last5_psa10"]:
        out["psa10_median5"] = statistics.median(out["last5_psa10"])
    if out["last5_psa9"]:
        out["psa9_median5"] = statistics.median(out["last5_psa9"])
    return out


# --- Main ---------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="Card name, e.g. \"Charizard ex\"")
    ap.add_argument("number", nargs="?", default=None, help="Card number as printed, e.g. 125/197")
    ap.add_argument("--set", dest="set_hint", default=None, help="Set name hint, e.g. \"Obsidian Flames\"")
    ap.add_argument("--debug", action="store_true", help="Dump raw API responses")
    args = ap.parse_args()

    print(f"Searching for: {args.name}  number={args.number}  set={args.set_hint}\n")
    try:
        card = search_tcg_card(args.name, args.number, args.set_hint)
    except requests.RequestException as e:
        sys.stderr.write(f"Pokemon TCG API failed: {e}\n")
        return 2

    if not card:
        print("No card found in Pokemon TCG API. Check spelling / number.")
        return 1

    cset = (card.get("set") or {}).get("name", "?")
    cnum = card.get("number", "?")
    print(f"Match: {card.get('name')}  |  {cset}  |  #{cnum}")
    if args.debug:
        print(json.dumps(card.get("tcgplayer") or {}, indent=2))

    raw_price = extract_tcg_market_price(card)
    if raw_price:
        print(f"Raw market (TCGPlayer):  ${raw_price:,.2f}")
    else:
        print("Raw market (TCGPlayer):  not available — look it up manually on tcgplayer.com")

    ppt = fetch_ppt_prices(args.name, args.number, args.set_hint)
    if ppt is None:
        print("\nPSA prices: PokemonPriceTracker disabled (no API key).")
        print("Get a free key at https://www.pokemonpricetracker.com and set POKEMONPRICETRACKER_API_KEY.")
        print("Manual fallback: search PriceCharting.com → take median of last 5 PSA 10 and PSA 9 sold prices.\n")
        psa10 = psa9 = psa8 = None
    else:
        psa10 = ppt.get("psa10_median5") or ppt.get("psa10")
        psa9 = ppt.get("psa9_median5") or ppt.get("psa9")
        psa8 = ppt.get("psa8")
        if args.debug:
            print(json.dumps(ppt.get("raw_record"), indent=2)[:2000])
        print()
        if psa10: print(f"PSA 10 ({'median of last 5' if ppt.get('psa10_median5') else 'latest'}): ${psa10:,.2f}")
        if psa9:  print(f"PSA 9  ({'median of last 5' if ppt.get('psa9_median5') else 'latest'}): ${psa9:,.2f}")
        if psa8:  print(f"PSA 8 fallback: ${psa8:,.2f}")

    # CSV output line you can paste in a sheet
    print("\nCSV (Card Name, Set, #, Notes, Raw, PSA10, PSA9, PSA<9, p10):")
    cols = [card.get("name", args.name), cset, cnum, "",
            f"{raw_price:.2f}" if raw_price else "",
            f"{psa10:.2f}" if psa10 else "",
            f"{psa9:.2f}" if psa9 else "",
            f"{psa8:.2f}" if psa8 else "",
            ""]
    print(",".join(str(x) for x in cols))
    return 0


if __name__ == "__main__":
    sys.exit(main())
