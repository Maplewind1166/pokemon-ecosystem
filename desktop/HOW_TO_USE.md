# Pokemon Decision Tools — How to Use

This folder is your personal Pokemon investment workstation. Open any file you need; nothing requires installation or accounts. Data stays in your browser.

## Files in this folder

- **`vault.html`** ← **start here**. The central dashboard: your collection, wishlist, P/L, settings.
- **`psa_decision_tool.html`** — the PSA-grade-vs-sell-raw decision tool (independent of the vault, will integrate in Phase 2).
- **`PSA_Decision_Workbook.xlsx`** — same PSA decision math as a spreadsheet, for batch evaluation or audit.
- **`price_lookup.py`** — small command-line helper to fetch prices from APIs (legacy from the PSA tool's early days).
- **Design docs:** `SUITE_DESIGN.md`, `VAULT_MVP_DESIGN.md`, `VAULT_BUILD_PLAN.md` — design references for the broader suite and the vault build plan.

---

## The Vault (`vault.html`) — primary tool

### Opening the vault

Double-click `vault.html`. It opens in your default browser and reads/writes to your browser's IndexedDB. Data persists between sessions on the same browser + same machine.

**If you see a CORS or network error on first load**, your browser is blocking `fetch()` from a `file://` URL. Fix: open a terminal in this folder and run `python -m http.server 8000`, then visit <http://localhost:8000/vault.html>. That's the recommended way to run it.

### Your first session

1. **Set your API key** (optional but recommended). Open ⚙ Settings → API keys → paste your free PokemonPriceTracker key (get one at <https://www.pokemonpricetracker.com/api-keys>, no credit card required). Save settings.

2. **Import your Collectr CSV**. Click 📥 Import (header or empty-state). Drag/drop your Collectr export. The 5-step wizard walks you through:
   - **Step 1:** Upload. Auto-validates Collectr headers.
   - **Step 2:** Filter & options. Pick which TCGs to import (defaults to Pokemon only — Collectr exports are multi-TCG). Choose how to handle duplicates on re-import.
   - **Step 3:** Column mapping. Pre-mapped from Collectr's standard headers; just confirm.
   - **Step 4:** Matching. Each Pokemon row hits the free Pokemon TCG API to get a card ID and image. ~15 seconds for ~100 cards. Other TCGs are imported as-is with the CSV's snapshot price.
   - **Step 5:** Review. Lists any rows that couldn't auto-match (typically <20% of Pokemon — usually recent promos). Click Finish.

3. **Refresh prices**. After import, the prices in the table reflect the CSV's "Market Price (As of ...)" snapshot. Click ↻ Refresh in the header to fetch live prices for stale cards from the APIs. The progress banner shows live counts.

4. **Build your wishlist**. Click the Wishlist tab → ➕ Add to wishlist. Search for the card, set a target buy price, optional max-pay ceiling, priority (1–5 stars), alert rule. Each item shows distance to target — green when at/below target (HIT), orange when within 10% (HOT), gray when farther.

5. **Back up**. Settings → Data → ⬇ Export JSON backup. Save the file somewhere safe — it's your full collection in one file. Restore via 📥 Restore from JSON.

### Day-to-day workflow

- **Add a single card** (just pulled, traded for, etc.): ➕ Add card → search → fill condition / cost basis / acquired date → save.
- **Refresh prices**: ↻ Refresh (header) or per-card via the row's ⋯ menu or detail panel's Refresh button. Auto-refresh on open is on by default (toggle in Settings).
- **Inspect a card**: click any row → detail panel slides in from the right with image, prices, history chart, lookup buttons (TCGPlayer / PriceCharting / PSA Analysis / eBay sold), Edit, Delete.
- **Edit a card**: row's ⋯ → Edit, or open detail panel → Edit. Identity (name/set/number) is fixed in edit mode; for those, delete and re-add.
- **Filter / search**: header search filters by name/set/number live. The filter bar above the table cuts by category, set, condition, tag, with sort options.
- **Force-refresh-everything**: Shift-click ↻ Refresh to ignore the cache and re-fetch every Pokemon card with a `tcg_id`. Useful after a market event.

### Portfolio header (top of Collection tab)

Four stat cells:

- **Total value** — `Σ quantity × last_market_price` over all cards with a market price. Sub-line shows how many are priced and the oldest refresh timestamp.
- **Cost basis** — `Σ quantity × cost_basis` across cards where you've entered a cost. Collectr's zero values import as `null` (untracked), so the cost is only counted where you actively recorded it.
- **Unrealized P/L** — total value minus cost basis, across cards that have both. Color-coded green/red. Sub-line shows count.
- **Total cards** — quantity-weighted, plus set count.

### Wishlist header

Total items · Hot (within 10% above target) · At/below target (HIT — ready to buy) · Total budget if you bought everything at target.

### Stale-price indicator

Cards whose `last_priced_at` is older than 2× your refresh interval show a ⚠ next to the market price. Hover to see the exact age. They still count in totals — the warning is just to know you haven't refreshed recently.

### Keyboard shortcuts

- `r` — Refresh all stale prices
- `n` — Open Add Card
- `/` — Focus the global search box
- `Esc` — Close any open panel or modal

---

## The PSA Decision Tool (`psa_decision_tool.html`)

A separate tool that decides, for a card you've already pulled, whether to PSA-grade it or sell it raw. Open `psa_decision_tool.html`. Search a card → fill prices → set your honest p(PSA 10) estimate → read the 5-tier verdict (Strong Grade / Weak Grade / Toss-up / Weak Sell / Strong Sell), breakeven probability, time-adjusted EV, and sensitivity chart. Save decisions; export to CSV.

The PSA tool currently has its own settings store. **Phase 2** will integrate it with the vault: clicking a card row's "Evaluate for PSA" will jump straight here pre-filled with the card's identity + cost, and decisions will get linked back to the vault.

---

## The Spreadsheet (`PSA_Decision_Workbook.xlsx`)

Same PSA-decision math as a workbook for batch evaluation or audit. Tabs: README, Settings, Card Decisions (30 rows of formulas), Glossary. Open in Excel or Google Sheets.

---

## Data backup & portability

Your vault data lives in your browser's IndexedDB — survives reloads, but is tied to this browser on this machine. To move between machines or browsers:

1. ⚙ Settings → Data → ⬇ Export JSON backup (uncheck "Include API keys" if sharing the file).
2. Move the backup file to the new machine / browser.
3. Open `vault.html` there, ⚙ Settings → Data → 📥 Restore from JSON → pick the file.

The backup includes cards, wishlist, full price history, import audits, and settings (minus API keys unless you explicitly include them).

**Cloud sync via Google Drive** is planned for Phase 8 (see `SUITE_DESIGN.md`).

---

## Privacy & data

- All data is local to your browser. Nothing leaves your machine except the API requests you trigger (Pokemon TCG API, PokemonPriceTracker — only when refreshing prices).
- API keys live in IndexedDB. JSON backups exclude them by default; you can opt to include them.
- 🗑 Clear all vault data wipes everything; requires typing the word `DELETE` to confirm.

---

## Troubleshooting

**"Network error on search" / "CORS error" when opening the file by double-click.**
Open a terminal in this folder and run `python -m http.server 8000`, then visit <http://localhost:8000/vault.html>. Some browsers block `fetch()` from `file://` URLs.

**Some imported cards have no `tcg_id` and no image.**
The Pokemon TCG API doesn't index every card (newest promos especially). Open the row's ⋯ → Edit, or use ➕ Add card's manual mode to relink it. The vault still tracks them — they just don't auto-refresh.

**Refresh runs but prices don't change.**
Likely the source returns the same value (low-volume cards rarely move day-to-day). Click an individual card's ↻ Refresh inside the detail panel to confirm the API call is working — watch the "refreshed Xs ago · source" caption update.

**Auto-refresh on open is annoying.**
Toggle off in ⚙ Settings → General → Refresh on open. You'll need to click ↻ Refresh manually when you want fresh prices.

**Lost my data after switching browsers.**
IndexedDB is per-browser. Export a JSON backup from the old browser, import it in the new one. Future Phase 8 will add Google Drive sync to remove this manual step.

**Want to delete a single price-history point.**
Not exposed in the UI for v1. In DevTools console: `await vault.db.prices.where({ tcg_id: '...', condition: '...' }).delete()` (replace with the values you want). Be careful.
