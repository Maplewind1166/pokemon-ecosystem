#!/usr/bin/env python3
"""
daily_agent.py — Pokemon vault daily price refresh + email digest.

Runs via GitHub Actions at 6 AM EST daily (cron: 0 11 * * *).

Reads vault_data.json from Google Drive, refreshes all card prices via
PokemonPriceTracker API (server-side, no CORS), writes updated vault back
to Drive, then emails an HTML digest.

Required secrets (set as GitHub Actions secrets):
  PPT_API_KEY             PokemonPriceTracker API key
  GDRIVE_SERVICE_ACCOUNT  Full contents of a Google service account JSON key
  SMTP_USER               Gmail address to send from
  SMTP_PASSWORD           Gmail App Password (not account password)
  DIGEST_TO               Recipient address (defaults to SMTP_USER)

Optional env vars:
  GDRIVE_FOLDER_NAME      Drive folder name (default: Pokemon Ecosystem)
  MAX_REFRESH             Max cards to price per run (default: 90, protects free tier)
  MOVER_THRESHOLD         % change to flag as a mover (default: 0.05 = 5%)
"""

from __future__ import annotations

import datetime
import io
import json
import os
import smtplib
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

try:
    import requests
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
except ImportError as e:
    sys.stderr.write(f"Missing dependency: {e}\nRun: pip install -r requirements.txt\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PPT_KEY           = os.environ.get("PPT_API_KEY", "").strip()
PPT_BASE          = "https://www.pokemonpricetracker.com/api/v2"
TCG_BASE          = "https://api.pokemontcg.io/v2"
DRIVE_FOLDER      = os.environ.get("GDRIVE_FOLDER_NAME", "Pokemon Ecosystem")
DRIVE_FILE        = "vault_data.json"
GDRIVE_SA_JSON    = os.environ.get("GDRIVE_SERVICE_ACCOUNT", "")
SMTP_HOST         = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT         = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER         = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD     = os.environ.get("SMTP_PASSWORD", "")
DIGEST_TO         = os.environ.get("DIGEST_TO", SMTP_USER)
MAX_REFRESH       = int(os.environ.get("MAX_REFRESH", "90"))
MOVER_THRESHOLD   = float(os.environ.get("MOVER_THRESHOLD", "0.05"))
API_TIMEOUT       = 20
PPT_DELAY         = 0.3  # seconds between PPT requests


# ---------------------------------------------------------------------------
# Google Drive helpers
# ---------------------------------------------------------------------------

def drive_service():
    if not GDRIVE_SA_JSON:
        raise ValueError(
            "GDRIVE_SERVICE_ACCOUNT env var is not set. "
            "Add the service account JSON as a GitHub secret."
        )
    info = json.loads(GDRIVE_SA_JSON)
    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def drive_get_folder_id(svc) -> str:
    resp = svc.files().list(
        q=f"name='{DRIVE_FOLDER}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id,name)",
        spaces="drive",
    ).execute()
    files = resp.get("files", [])
    if not files:
        raise FileNotFoundError(
            f"Google Drive folder '{DRIVE_FOLDER}' not found. "
            "Share it with the service account's email address."
        )
    return files[0]["id"]


def drive_get_file_id(svc, folder_id: str) -> Optional[str]:
    resp = svc.files().list(
        q=f"name='{DRIVE_FILE}' and '{folder_id}' in parents and trashed=false",
        fields="files(id,name,modifiedTime)",
        spaces="drive",
    ).execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def drive_download(svc, file_id: str) -> dict:
    buf = io.BytesIO()
    request = svc.files().get_media(fileId=file_id)
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return json.loads(buf.read())


def drive_upload(svc, folder_id: str, file_id: Optional[str], data: dict):
    blob = json.dumps(data, indent=2).encode()
    media = MediaIoBaseUpload(io.BytesIO(blob), mimetype="application/json", resumable=False)
    if file_id:
        svc.files().update(fileId=file_id, media_body=media).execute()
    else:
        meta = {"name": DRIVE_FILE, "parents": [folder_id]}
        svc.files().create(body=meta, media_body=media, fields="id").execute()


# ---------------------------------------------------------------------------
# Price fetching
# ---------------------------------------------------------------------------

def ppt_fetch_price(card: dict) -> tuple[Optional[float], str]:
    """
    Returns (market_price, source) or (None, '') on failure.
    source == 'rate_limited' signals the caller to stop further PPT calls.
    """
    if not PPT_KEY:
        return None, ""
    if card.get("ppt_id"):
        endpoint = f"/cards?id={card['ppt_id']}&limit=1"
    elif card.get("tcg_id"):
        endpoint = f"/cards?tcgPlayerId={card['tcg_id']}&limit=1"
    else:
        return None, ""

    headers = {"Authorization": f"Bearer {PPT_KEY}"}
    try:
        r = requests.get(PPT_BASE + endpoint, headers=headers, timeout=API_TIMEOUT)
        if r.status_code == 429:
            print("  PPT: 429 rate limited — stopping PPT calls for this run")
            return None, "rate_limited"
        if not r.ok:
            return None, ""
        body = r.json()
        items = body if isinstance(body, list) else (
            body.get("data") or body.get("cards") or body.get("results") or []
        )
        if not items:
            return None, ""
        c = items[0]
        prices = c.get("prices") or {}
        raw = prices.get("market") or prices.get("marketPrice") or c.get("marketPrice")
        if raw is not None:
            return float(raw), "ppt"
    except Exception as e:
        print(f"  PPT error for '{card.get('name')}': {e}")
    return None, ""


def tcg_fetch_price(card: dict) -> tuple[Optional[float], str]:
    """Fallback to Pokemon TCG API for cards with a tcg_id."""
    if not card.get("tcg_id"):
        return None, ""
    try:
        r = requests.get(f"{TCG_BASE}/cards/{card['tcg_id']}", timeout=API_TIMEOUT)
        if not r.ok:
            return None, ""
        data = r.json().get("data") or {}
        prices = (data.get("tcgplayer") or {}).get("prices") or {}
        for variant in ("holofoil", "1stEditionHolofoil", "reverseHolofoil", "normal", "unlimitedHolofoil"):
            v = prices.get(variant) or {}
            if v.get("market"):
                return float(v["market"]), "pokemontcg"
        for v in prices.values():
            if isinstance(v, dict) and v.get("market"):
                return float(v["market"]), "pokemontcg"
    except Exception as e:
        print(f"  TCG API error for '{card.get('name')}': {e}")
    return None, ""


# ---------------------------------------------------------------------------
# Price refresh
# ---------------------------------------------------------------------------

def refresh_prices(vault: dict) -> tuple[dict, list[dict]]:
    """
    Refresh prices for eligible cards (Pokemon, has tcg_id or ppt_id).
    Returns the mutated vault and a list of result dicts for the digest.
    """
    cards = vault.get("cards", [])
    prices_log: list[dict] = vault.get("prices", [])

    eligible = [
        c for c in cards
        if c.get("category") == "Pokemon" and (c.get("tcg_id") or c.get("ppt_id"))
    ]

    # Oldest-first so freshest cards are protected when we hit MAX_REFRESH
    eligible.sort(key=lambda c: c.get("last_priced_at") or "")

    to_refresh = eligible[:MAX_REFRESH]
    skipped_count = len(eligible) - len(to_refresh)
    if skipped_count:
        print(f"  Vault has {len(eligible)} priceable cards; refreshing oldest {MAX_REFRESH} (MAX_REFRESH limit)")

    results: list[dict] = []
    rate_limited = False

    for card in to_refresh:
        name = card.get("name", card.get("id", "?"))
        old_price = card.get("last_market_price")

        if rate_limited:
            results.append({"id": card["id"], "name": name, "error": "skipped_rate_limit"})
            continue

        print(f"  Pricing: {name} ({card.get('set', '')} #{card.get('number', '?')})")

        price, source = ppt_fetch_price(card)

        if source == "rate_limited":
            rate_limited = True
            results.append({"id": card["id"], "name": name, "error": "rate_limited"})
            continue

        if price is None:
            price, source = tcg_fetch_price(card)

        ts = datetime.datetime.utcnow().isoformat() + "Z"

        if price is not None:
            pct_change: Optional[float] = None
            if old_price and old_price > 0:
                pct_change = (price - old_price) / old_price

            card["last_market_price"] = price
            card["last_priced_at"] = ts
            card["last_price_source"] = source
            card["updated_at"] = ts

            prices_log.append({
                "tcg_id": card.get("tcg_id"),
                "ppt_id": card.get("ppt_id"),
                "card_id": card.get("id"),
                "condition": card.get("condition"),
                "ts": ts,
                "price": price,
                "source": source,
            })

            results.append({
                "id": card["id"],
                "name": name,
                "set": card.get("set", ""),
                "old_price": old_price,
                "new_price": price,
                "pct_change": pct_change,
                "source": source,
            })
        else:
            results.append({
                "id": card["id"],
                "name": name,
                "set": card.get("set", ""),
                "old_price": old_price,
                "error": "no_price_found",
            })

        time.sleep(PPT_DELAY)

    vault["prices"] = prices_log
    vault["exported_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    return vault, results


# ---------------------------------------------------------------------------
# Wishlist hit check
# ---------------------------------------------------------------------------

def check_wishlist(vault: dict) -> list[dict]:
    """Return wishlist entries at or below their target price."""
    wishlist = vault.get("wishlist", [])
    if not wishlist:
        return []

    # Build tcg_id → current price map from refreshed cards
    price_by_tcg: dict[str, float] = {}
    for card in vault.get("cards", []):
        tcg_id = card.get("tcg_id")
        price = card.get("last_market_price")
        if tcg_id and price is not None:
            price_by_tcg[tcg_id] = price

    hits = []
    for item in wishlist:
        target = item.get("target_buy_price")
        if not target or target <= 0:
            continue
        tcg_id = item.get("tcg_id")
        market = price_by_tcg.get(tcg_id) if tcg_id else None
        if market is None:
            continue
        if market <= target:
            hits.append({
                "name": item.get("name", "Unknown"),
                "set": item.get("set", ""),
                "number": item.get("number", ""),
                "target": target,
                "market": market,
                "gap": round(target - market, 2),
            })

    hits.sort(key=lambda h: -(h["gap"]))
    return hits


# ---------------------------------------------------------------------------
# Top gains / TCGPlayer gap
# ---------------------------------------------------------------------------

def top_gains(vault: dict, n: int = 5) -> list[dict]:
    """Cards with the highest unrealized % gain (selling opportunities)."""
    out = []
    for card in vault.get("cards", []):
        cost = card.get("cost_basis")
        price = card.get("last_market_price")
        if not cost or cost <= 0 or price is None:
            continue
        qty = card.get("quantity") or 1
        pct = (price - cost) / cost
        out.append({
            "name": card.get("name", "?"),
            "set": card.get("set", ""),
            "cost": cost,
            "price": price,
            "gain": round((price - cost) * qty, 2),
            "pct": pct,
        })
    out.sort(key=lambda x: -x["pct"])
    return out[:n]


# ---------------------------------------------------------------------------
# Email HTML
# ---------------------------------------------------------------------------

def _fmt_price(p: Optional[float]) -> str:
    return f"${p:,.2f}" if p is not None else "—"


def _fmt_pct(p: Optional[float]) -> str:
    if p is None:
        return ""
    sign = "+" if p >= 0 else ""
    return f"{sign}{p * 100:.1f}%"


def _pct_color(p: Optional[float]) -> str:
    if p is None:
        return "#666"
    return "#16a34a" if p >= 0 else "#dc2626"


_TABLE_TH = "padding:6px 8px;text-align:{align};font-weight:600;background:#f8f8f8;border-bottom:2px solid #e5e7eb;"
_TABLE_TD = "padding:6px 8px;border-bottom:1px solid #f0f0f0;{extra}"


def _mover_table(rows_html: str, label: str, color: str) -> str:
    return f"""
    <p style="color:{color};font-weight:600;margin:12px 0 4px;">{label}</p>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <tr>
        <th style="{_TABLE_TH.format(align='left')}">Card</th>
        <th style="{_TABLE_TH.format(align='left')}">Set</th>
        <th style="{_TABLE_TH.format(align='right')}">Before</th>
        <th style="{_TABLE_TH.format(align='right')}">After</th>
        <th style="{_TABLE_TH.format(align='right')}">Change</th>
      </tr>
      {rows_html}
    </table>"""


def build_email(vault: dict, results: list[dict], wishlist_hits: list[dict], run_ts: str) -> str:
    cards = vault.get("cards", [])
    pokemon_cards = [c for c in cards if c.get("category") == "Pokemon"]

    total_value = sum((c.get("last_market_price") or 0) * (c.get("quantity") or 1) for c in pokemon_cards)
    total_cost  = sum((c.get("cost_basis") or 0) * (c.get("quantity") or 1) for c in pokemon_cards)
    total_pl    = total_value - total_cost
    pl_pct      = (total_pl / total_cost * 100) if total_cost > 0 else 0
    pl_color    = "#16a34a" if total_pl >= 0 else "#dc2626"
    pl_sign     = "+" if total_pl >= 0 else ""

    refreshed   = [r for r in results if "new_price" in r]
    errors      = [r for r in results if r.get("error") not in (None, "skipped_rate_limit")]
    movers_up   = sorted(
        [r for r in refreshed if (r.get("pct_change") or 0) >= MOVER_THRESHOLD],
        key=lambda x: -(x.get("pct_change") or 0),
    )
    movers_down = sorted(
        [r for r in refreshed if (r.get("pct_change") or 0) <= -MOVER_THRESHOLD],
        key=lambda x: (x.get("pct_change") or 0),
    )

    def mover_row(r: dict) -> str:
        pct = r.get("pct_change")
        return (
            f"<tr>"
            f"<td style='{_TABLE_TD.format(extra='')}'>{r.get('name','?')}</td>"
            f"<td style='{_TABLE_TD.format(extra='color:#888;font-size:12px;')}'>{r.get('set','')}</td>"
            f"<td style='{_TABLE_TD.format(extra='text-align:right;')}'>{_fmt_price(r.get('old_price'))}</td>"
            f"<td style='{_TABLE_TD.format(extra='text-align:right;')}'>{_fmt_price(r.get('new_price'))}</td>"
            f"<td style='{_TABLE_TD.format(extra=f'text-align:right;color:{_pct_color(pct)};font-weight:600;')}'>"
            f"{_fmt_pct(pct)}</td>"
            f"</tr>"
        )

    # --- Mover section ---
    mover_html = ""
    if movers_up:
        mover_html += _mover_table("".join(mover_row(r) for r in movers_up), "▲ Up (≥5%)", "#16a34a")
    if movers_down:
        mover_html += _mover_table("".join(mover_row(r) for r in movers_down), "▼ Down (≥5%)", "#dc2626")
    if not movers_up and not movers_down:
        mover_html = "<p style='color:#888;font-size:13px;'>No significant price movers today (threshold: ±5%).</p>"

    # --- Wishlist section ---
    wishlist_html = ""
    if wishlist_hits:
        wl_rows = "".join(
            f"<tr>"
            f"<td style='{_TABLE_TD.format(extra='')}'>{h['name']}</td>"
            f"<td style='{_TABLE_TD.format(extra='color:#888;font-size:12px;')}'>{h.get('set','')}</td>"
            f"<td style='{_TABLE_TD.format(extra='text-align:right;')}'>{_fmt_price(h['target'])}</td>"
            f"<td style='{_TABLE_TD.format(extra='text-align:right;color:#16a34a;font-weight:600;')}'>{_fmt_price(h['market'])}</td>"
            f"<td style='{_TABLE_TD.format(extra='text-align:right;color:#16a34a;')}'>{_fmt_price(h['gap'])} under</td>"
            f"</tr>"
            for h in wishlist_hits
        )
        wishlist_html = f"""
        <h2 style="color:#1a1a1a;font-size:15px;margin:24px 0 8px;">🎯 Wishlist Hits ({len(wishlist_hits)})</h2>
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
          <tr>
            <th style="{_TABLE_TH.format(align='left')}">Card</th>
            <th style="{_TABLE_TH.format(align='left')}">Set</th>
            <th style="{_TABLE_TH.format(align='right')}">Target</th>
            <th style="{_TABLE_TH.format(align='right')}">Market</th>
            <th style="{_TABLE_TH.format(align='right')}">Gap</th>
          </tr>
          {wl_rows}
        </table>"""

    # --- Top gains section ---
    gains = top_gains(vault)
    gains_html = ""
    if gains:
        gain_rows = "".join(
            f"<tr>"
            f"<td style='{_TABLE_TD.format(extra='')}'>{g['name']}</td>"
            f"<td style='{_TABLE_TD.format(extra='color:#888;font-size:12px;')}'>{g.get('set','')}</td>"
            f"<td style='{_TABLE_TD.format(extra='text-align:right;')}'>{_fmt_price(g['cost'])}</td>"
            f"<td style='{_TABLE_TD.format(extra='text-align:right;')}'>{_fmt_price(g['price'])}</td>"
            f"<td style='{_TABLE_TD.format(extra=f'text-align:right;color:#16a34a;font-weight:600;')}'>"
            f"+{_fmt_price(g['gain'])} ({_fmt_pct(g['pct'])})</td>"
            f"</tr>"
            for g in gains
        )
        gains_html = f"""
        <h2 style="color:#1a1a1a;font-size:15px;margin:24px 0 8px;">💰 Top Gains (TCGPlayer Opportunities)</h2>
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
          <tr>
            <th style="{_TABLE_TH.format(align='left')}">Card</th>
            <th style="{_TABLE_TH.format(align='left')}">Set</th>
            <th style="{_TABLE_TH.format(align='right')}">Cost</th>
            <th style="{_TABLE_TH.format(align='right')}">Market</th>
            <th style="{_TABLE_TH.format(align='right')}">Gain</th>
          </tr>
          {gain_rows}
        </table>"""

    # --- Error section ---
    error_html = ""
    if errors:
        names = ", ".join(r.get("name", r.get("id", "?")) for r in errors[:10])
        if len(errors) > 10:
            names += f" (+{len(errors) - 10} more)"
        error_html = f"""
        <h2 style="color:#1a1a1a;font-size:15px;margin:24px 0 8px;">⚠ Pricing Failures ({len(errors)})</h2>
        <p style="color:#dc2626;font-size:13px;margin:0 0 4px;">{names}</p>
        <p style="color:#888;font-size:12px;margin:0;">Re-link these cards in the vault via Add Card search.</p>"""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,sans-serif;background:#f0f2f5;margin:0;padding:20px;">
  <div style="max-width:620px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.12);">

    <div style="background:linear-gradient(135deg,#1e3a5f 0%,#2d5fa6 100%);padding:24px;color:#fff;">
      <div style="font-size:20px;font-weight:700;letter-spacing:-.3px;">Pokemon Vault — Daily Digest</div>
      <div style="font-size:13px;opacity:.75;margin-top:4px;">{run_ts}</div>
    </div>

    <div style="padding:18px 24px;background:#f8fafc;border-bottom:1px solid #e5e7eb;display:flex;gap:0;flex-wrap:wrap;">
      <div style="flex:1;min-width:140px;padding:4px 16px 4px 0;">
        <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.07em;margin-bottom:2px;">Portfolio Value</div>
        <div style="font-size:22px;font-weight:700;color:#111;">{_fmt_price(total_value)}</div>
      </div>
      <div style="flex:1;min-width:140px;padding:4px 16px;">
        <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.07em;margin-bottom:2px;">Cost Basis</div>
        <div style="font-size:22px;font-weight:700;color:#111;">{_fmt_price(total_cost)}</div>
      </div>
      <div style="flex:1;min-width:140px;padding:4px 0 4px 16px;">
        <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.07em;margin-bottom:2px;">Unrealized P/L</div>
        <div style="font-size:22px;font-weight:700;color:{pl_color};">{pl_sign}{_fmt_price(abs(total_pl))} ({pl_sign}{pl_pct:.1f}%)</div>
      </div>
    </div>
    <div style="padding:6px 24px 12px;background:#f8fafc;border-bottom:1px solid #e5e7eb;font-size:12px;color:#999;">
      {len(refreshed)} of {len(pokemon_cards)} cards refreshed today
      {f" · {len(wishlist_hits)} wishlist hit(s)" if wishlist_hits else ""}
      {f" · ⚠ {len(errors)} pricing failure(s)" if errors else ""}
    </div>

    <div style="padding:20px 24px;">
      {wishlist_html}
      <h2 style="color:#1a1a1a;font-size:15px;margin:{'24px' if wishlist_html else '4px'} 0 8px;">Price Movers</h2>
      {mover_html}
      {gains_html}
      {error_html}
    </div>

    <div style="padding:14px 24px;background:#f8f8f8;border-top:1px solid #e5e7eb;font-size:11px;color:#aaa;">
      Pokemon Ecosystem daily agent &middot; Prices via PokemonPriceTracker.com
    </div>

  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Email dispatch
# ---------------------------------------------------------------------------

def send_email(subject: str, html_body: str):
    if not SMTP_USER or not SMTP_PASSWORD:
        print("SMTP not configured — skipping email (set SMTP_USER and SMTP_PASSWORD secrets).")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = DIGEST_TO
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.ehlo()
        s.starttls()
        s.login(SMTP_USER, SMTP_PASSWORD)
        s.sendmail(SMTP_USER, DIGEST_TO, msg.as_string())
    print(f"Email sent to {DIGEST_TO}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    run_ts = datetime.datetime.utcnow().strftime("%B %d, %Y at %I:%M %p UTC")
    print(f"=== Pokemon Vault Daily Agent — {run_ts} ===")

    # Connect to Drive
    print("\n[1/5] Connecting to Google Drive...")
    svc       = drive_service()
    folder_id = drive_get_folder_id(svc)
    file_id   = drive_get_file_id(svc, folder_id)

    if not file_id:
        print("No vault_data.json found on Drive. Open the vault and sync to Drive first.")
        return

    # Download vault
    print("[2/5] Downloading vault_data.json...")
    vault = drive_download(svc, file_id)
    n_cards  = len(vault.get("cards", []))
    n_prices = len(vault.get("prices", []))
    print(f"  Loaded {n_cards} cards, {n_prices} existing price history points")

    # Refresh prices
    print(f"\n[3/5] Refreshing prices (PPT API, max {MAX_REFRESH} cards)...")
    vault, results = refresh_prices(vault)
    refreshed = [r for r in results if "new_price" in r]
    errors    = [r for r in results if r.get("error") not in (None, "skipped_rate_limit")]
    print(f"  Done: {len(refreshed)} refreshed, {len(errors)} failed")

    # Check wishlist
    print("\n[4/5] Checking wishlist...")
    wishlist_hits = check_wishlist(vault)
    print(f"  Wishlist hits: {len(wishlist_hits)}")

    # Upload updated vault
    print("\n[5/5] Uploading updated vault to Drive...")
    drive_upload(svc, folder_id, file_id, vault)
    print("  Upload complete.")

    # Build and send email
    html = build_email(vault, results, wishlist_hits, run_ts)
    movers = [r for r in refreshed if abs(r.get("pct_change") or 0) >= MOVER_THRESHOLD]
    subject_parts = [f"Pokemon Vault [{datetime.datetime.utcnow().strftime('%b %d')}]"]
    if wishlist_hits:
        subject_parts.append(f"{len(wishlist_hits)} wishlist hit(s)")
    if movers:
        subject_parts.append(f"{len(movers)} mover(s)")
    subject = " — ".join(subject_parts)
    send_email(subject, html)

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
