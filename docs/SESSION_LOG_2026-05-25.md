# Pokemon Ecosystem — Session Log
*Date: May 25, 2026*

---

## Session Goals
- Verify promo card fix from previous session
- Build Phase 2: PSA Advisor tab integrated into vault.html
- Add selective refresh to protect PPT API credits
- Add collection filter improvements

---

## 1. Verified from Previous Session

- **Mega Charizard X ex 023 promo** now appears correctly in Add Card search
- **Duplicate cards** issue resolved — deduplication by `tcgPlayerId` confirmed working
- English and Japanese versions correctly show as separate cards (expected behavior)

---

## 2. Phase 2: PSA Advisor Tab — Completed

### What was built
The standalone `psa_decision_tool.html` is now fully integrated into `vault.html`
as a third tab: **🎯 PSA Advisor**. The standalone file can now be retired.

### Features
- **Standalone search** — search any card from scratch (for purchase decisions)
- **Pre-fill from vault card** — click 🎯 PSA Eval in any card's detail panel →
  PSA tab opens with that card's identity and market price pre-filled
- **Pre-fill banner** — blue banner confirms which vault card launched the eval
- **Full EV math** — same `psaCompute()` engine as original tool (5-tier verdict,
  time-adjusted breakeven, sensitivity chart)
- **PSA price auto-fetch** — uses PPT API via CORS proxy to attempt PSA 9/10 fill
- **Decision history** — saved to vault's IndexedDB (not localStorage), persists
  with vault data. Linked to vault card via `vaultCardId` field.
- **CSV export** — full decision history downloadable
- **Settings sidebar** — all PSA/TCG fee settings editable inline, saves to
  vault's shared settings store (same as ⚙ Settings panel)
- **Clear state on launch** — previous search results wiped when launching from
  a vault card (fixed during session)

### Key implementation notes
- PSA JS lives in vault.html after the `// END` marker, before `DOMContentLoaded`
- `initPsaTab()` called lazily on first tab open (not on vault load)
- PSA history stored as JSON blob in `settings` IndexedDB table under key
  `psa_decision_history` — avoids adding a new Dexie table
- All PSA functions prefixed `psa` to avoid name collision with vault globals
- `psaCoreName()` strips variant prefixes for PSA Analysis URL
- `psaFetchFullCard()` reuses vault's `pptFetch()` helper (CORS proxy included)
- Settings read/write via vault's `getSettings()` / `updateSettings()`

### HTML elements added
- Nav: `<button data-tab="psa">🎯 PSA Advisor</button>`
- Detail panel: `<button id="cd-psa-eval-btn">🎯 PSA Eval</button>`
- New section: `<section id="psa-tab">` (full layout inside main)

### switchTab updated
```javascript
document.getElementById('psa-tab').hidden = (tab !== 'psa');
if (tab === 'psa') await initPsaTab();
```

---

## 3. Selective Refresh — Completed

### Problem
Auto-refresh on open would consume all 100 daily PPT credits with a large vault.
Even manual "Refresh All" was dangerous — no credit visibility before running.

### Solution: Split refresh button with dropdown

The single `↻ Refresh` button replaced with a split button:

```
↻ Refresh stale  ▾
                  ├── ↻ Refresh stale only   (default)
                  ├── ⟳ Force refresh all    (ignores staleness cutoff)
                  └── 📅 Refresh oldest 20   (credit-safe, always ≤20 credits)
```

**Refresh stale only** — only cards older than `refresh_interval_hours` (default 24h).
**Force refresh all** — every card regardless of age (use after market events).
**Refresh oldest 20** — sorts by `last_priced_at` ascending, takes first 20.
This is the safest option for large vaults on the free PPT tier.

### Credit estimate shown before every refresh
```
Refresh 45 cards?
~45 PPT credits will be used (100/day free).
Estimated time: ~90s
[OK] [Cancel]
```
Warning shown if batch would use >80 credits:
```
⚠️ This will use ~95 of your 100 daily PPT credits.
```
No confirmation shown for ≤5 cards (single card refresh from detail panel).

### Bug fix included
Cards with `ppt_id` only (promo cards, no `tcg_id`) were silently excluded from
all refresh candidates. Fixed: candidates now include `c.tcg_id || c.ppt_id`.

### Auto-refresh
Already disabled in previous session via ⚙ Settings → uncheck "Refresh on open".
`maybeAutoRefreshOnOpen()` respects this setting.

### Keyboard shortcut
`r` key still triggers "Refresh stale only" (main button click).

---

## 4. Collection Filter Improvements — Completed

### Three new filters added to the filter bar

**Price ≥ $X** (numeric input)
- Type any dollar amount → instantly hides cards below that price
- Uses `last_market_price` field
- Empty field = no filter

**Top 20 quick filter** (toggle button)
- Click `Top 20` → button turns blue (active state)
- Table shows only the 20 most valuable cards, sorted by total value descending
- Click again to toggle off
- Overrides sort order while active (always sorts by value desc)

**🏷 Listed quick filter** (toggle button)
- Click `🏷 Listed` → button turns blue
- Shows only cards where `listed_on_tcgplayer = true`
- Uses existing `filterState.location === 'listed'` path (already in applyFilters)
- Also syncs with the Location dropdown

**Clear filters** resets all three new filters plus existing ones.

### filterState additions
```javascript
minPrice: null,  // number or null
topN: null       // number (20) or null
```

### applyFilters addition
```javascript
if (filterState.minPrice != null) {
  if (c.last_market_price == null || c.last_market_price < filterState.minPrice) return false;
}
```

### sortCards addition
```javascript
if (topN) {
  return cards.slice()
    .sort((a, b) => (getCardMetrics(b).value ?? -Infinity) - (getCardMetrics(a).value ?? -Infinity))
    .slice(0, topN);
}
```

---

## 5. Settings Reminder

**Auto-refresh is OFF** — must refresh manually via the ↻ button.
**PPT API key** must be re-entered after any browser/machine change (stored in IndexedDB).
**Current PPT key:** `pokeprice_free_e59ae7774acb3da38410ee3ada1ad6bd0d18be4aeb29ccb9`
**Free tier:** 100 credits/day, resets at midnight UTC (7 PM EST).

---

## 6. Files Retired

- `psa_decision_tool.html` — functionality fully integrated into `vault.html`.
  Keep the file in `desktop/` for reference but it is no longer needed for use.

---

## 7. Git Commits This Session

```
Add selective refresh, price filters, top 20, listed filter, PSA tab integration
```

---

## 8. Next Steps

### Immediate
- [ ] Add more cards to vault (promo cards now work)
- [ ] Test PSA Advisor with a real card evaluation end-to-end

### Phase 3: Google Drive Sync
- Target: vault data syncs to Drive automatically across all 3 Macs
- Requires: Google Cloud project + OAuth 2.0 credentials (one-time setup)
- Benefit: open vault.html on any Mac, data is always current
- Also needed by: Phase 4 daily agent (agent reads/writes Drive JSON)
- Build in: this Claude Project chat

### Phase 4: Daily Agent
- Python script runs at 6 AM via GitHub Actions (free)
- Fetches prices server-side (no CORS, no browser credit usage)
- Writes updated prices to Drive JSON
- Sends HTML email digest with movers, wishlist hits, TCGPlayer gaps
- Build in: Claude Code

### Phase 5: Mobile PWA
- Camera → card identification via Claude Vision
- Reads/writes same Drive JSON as desktop vault
- Build in: this Claude Project chat

---

*Next session: Phase 3 — Google Drive sync setup*
