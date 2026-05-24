# Vault MVP — Build Plan

The last design artifact before code. This is the concrete answer to "how do we get from VAULT_MVP_DESIGN.md to a working `vault.html`?"

---

## Philosophy

**Ship a thin slice end-to-end first.** It's tempting to build the perfect schema, then the perfect table, then the perfect import wizard. Instead, we'll build the *narrowest* version of each layer that supports a real user flow, then iterate. The first checkpoint is "I can add one card by hand and see it in a table after refresh." Each later milestone makes that flow richer.

**No premature abstraction.** Reuse code from the PSA tool by copy-paste, not by extracting a shared library. The refactor into a shared `lib.js` becomes a Phase 2 chore when both tools have to be touched together — until then, two tools that each work is better than one shared abstraction we have to maintain.

**Every milestone is verifiable in <2 minutes.** No "trust me, this part works." Each step ends with a concrete check the user can run in their browser.

---

## File structure

Single self-contained HTML file, same paradigm as the PSA tool:

```
Pokemon Decision/
├── psa_decision_tool.html     (existing)
├── vault.html                  ← NEW, this build
├── SUITE_DESIGN.md
├── VAULT_MVP_DESIGN.md
├── VAULT_BUILD_PLAN.md         (this file)
├── HOW_TO_USE.md               (updated to cover both tools)
├── PSA_Decision_Workbook.xlsx
└── price_lookup.py
```

Inside `vault.html`:

```
<head>
  <style>            inline CSS — same aesthetic as psa_decision_tool
  <script src=...>   Chart.js (CDN)
  <script src=...>   Dexie.js — IndexedDB wrapper (CDN, ~50KB)
  <script src=...>   Papa Parse — CSV parser (CDN, ~40KB)
</head>
<body>
  ... markup for all 7 screens, hidden/shown via classes ...
  <script>
    // 1. Schema + Dexie setup
    // 2. Storage layer (cards, wishlist, prices, settings, audits CRUD)
    // 3. External APIs (Pokemon TCG, PPT) — copied from psa_decision_tool
    // 4. Math/helpers (median, format, etc.)
    // 5. UI: empty state
    // 6. UI: main table + portfolio header + filters
    // 7. UI: card detail panel
    // 8. UI: add/edit modal
    // 9. UI: import wizard (5 steps)
    // 10. UI: wishlist tab
    // 11. UI: settings panel
    // 12. Init + routing
  </script>
</body>
```

Approximate final size: 3000–4500 lines. Larger than the PSA tool, still navigable as one file.

---

## Build order — 10 milestones

Each milestone is a stop-and-verify point. The user clicks something specific and confirms it works before moving on.

### Milestone 1 — Skeleton + Dexie schema (foundation)

**Build**

- Empty `vault.html` with light/dark-mode-friendly CSS, header bar, footer, single empty "Collection" tab placeholder.
- Inline Dexie setup with all 5 object stores (`cards`, `wishlist`, `prices`, `settings`, `import_audits`) + indexes from the design doc.
- Singleton settings record initialized with defaults on first run.
- A tiny debug console: `window.vault = { db, listCards: () => db.cards.toArray(), ... }` exposed for inspection.

**Verify**

- Open the file. Browser DevTools → Application → IndexedDB → `pokemonVault` shows all 5 stores.
- In DevTools console: `await vault.listCards()` returns `[]`. `await vault.settings()` returns the defaults.

**Why first:** if Dexie / IndexedDB doesn't work in the user's browser configuration, everything else is wasted effort. We catch the worst-case (private-mode browser) up front.

---

### Milestone 2 — Empty state + Settings panel

**Build**

- Empty-state screen rendering when `cards` is empty: "Your vault is empty. Import CSV or Add card."
- Settings slide-in panel with all sections from Screen 7: general, API keys, pricing source priority, PSA tool defaults (stub for now), data section.
- Settings save/load to/from the singleton record.

**Verify**

- Open the file → empty state appears.
- Click ⚙ → settings panel opens. Type in the PokemonPriceTracker key, click Save.
- Refresh page → settings panel still shows the saved key. Confirms IndexedDB persistence end-to-end.

---

### Milestone 3 — Add card manually (search + form)

**Build**

- Add card modal with the two-mode radio (Search / Manual).
- Search mode: copy-paste the entire `searchPokemonTcg` + `searchPokemonPriceTracker` + result-rendering code from `psa_decision_tool.html`. Renders result tiles; clicking a tile fills the identity fields.
- Manual mode: raw inputs for name / set / number / variant / image upload.
- Bottom form: condition (full dropdown), quantity, cost basis, acquired on, acquired from, tags, notes.
- Save handler writes a card record to IndexedDB.

**Verify**

- Click "Add card" from empty state → modal opens.
- Search "charizard ex" → results render.
- Click one → identity fields fill, set condition to PSA 10, qty 1, cost basis $40, save.
- Refresh page → empty state is gone, replaced by a minimal placeholder ("1 card in vault — table coming next milestone"). Confirms write path.

---

### Milestone 4 — Main table view + portfolio header + filters

**Build**

- Render the main table (all columns from the design doc): image thumbnail, name, set, #, condition badge, qty, cost basis, market, value, P/L $, P/L %, tags, action menu.
- Portfolio header with total value, cost basis, unrealized P/L (computed on render).
- Filter bar: set, condition, tag, value range, sort dropdown.
- View toggle: Table (default) / Gallery — gallery view is a "stretch" within this milestone; ship if quick, defer if it takes >30 min.
- Empty-table-after-filters state with "Clear filters" button.

**Verify**

- Add 5 cards via the modal (mix of conditions and sets).
- Table renders with all 5 rows. Portfolio header shows totals.
- Filter by set → only matching cards remain. Sort by P/L → order changes.
- Click "Clear filters" → all 5 back. Refresh page → state survives.

---

### Milestone 5 — Card detail panel

**Build**

- Right-side slide-in panel (~520px wide) bound to the currently-clicked row.
- All sections from Screen 3: image, identity, condition+qty+cost+market+P/L block, price-history mini-chart (Chart.js), tags, notes, external lookup buttons (TCGPlayer / PriceCharting / PSA Analysis — reuse the URL builders from the PSA tool), "Linked decisions" placeholder, action buttons (refresh, edit, delete).
- Edit button → reopens the add/edit modal pre-filled.
- Delete button → confirmation dialog → removes from IndexedDB.
- Refresh price button (single-card variant) — calls Pokemon TCG API + PPT in turn, writes a new `prices` row + updates `cards.last_market_price`.

**Verify**

- Click a row → panel opens with all the details.
- Click "Refresh price" → market value updates, "Refreshed Xs ago" timestamp changes.
- Edit → change condition → save → table row reflects change.
- Delete → row disappears, panel closes.

**Note on price history:** the mini-chart will show "Need more history" until we have ≥2 `prices` rows. Wait until Milestone 8 (refresh logic) to see a real curve; for now, verify the chart container renders and stays empty without erroring.

---

### Milestone 6 — Import wizard (5 steps)

**Build**

- Modal with 5 sub-screens, navigable forward/back.
- Step 1: file drop / picker. Papa Parse on the uploaded file. Validates: expected ≥1 row, expected column headers (warn if mismatch but allow proceed).
- Step 2: category filter checkboxes (with row counts), watchlist handling, duplicate handling.
- Step 3: column-mapping table, fully auto-populated for the Collectr format. Parsing rules listed inline (the box from the design doc).
- Step 4: batch resolution loop. For Pokemon rows, queue 1 API call per row to `searchPokemonTcg(name, number)` with the row's name+number — pick the highest-confidence match. Progress bar updates. For non-Pokemon rows, skip the lookup (record stays with provided identity + null `tcg_id`).
- Step 5: review screen with unmatched-row list, each with Search/Manual links. Final "Finish" writes everything to `cards` + records the audit row.

**Verify**

- Import the user's real `export.csv` (547 rows). Default filters: Pokemon-only. Watchlist: skip.
- Step 1: file accepted, row count detected.
- Step 2: 7 categories, Pokemon checkbox shows 94 rows.
- Step 3: column mapping looks right.
- Step 4: progress bar runs, some matches succeed, some flagged unmatched.
- Step 5: review screen lists unmatched rows. Click Finish.
- Open table → ~89/94 Pokemon cards present (matched), 5 unmatched shown with a ⚠ icon for manual fix.
- Portfolio header: totals look right.

**Risk:** the most complex milestone. Likely to take twice as long as other milestones. We accept that and plan a checkpoint mid-build (e.g., Steps 1–3 done = pause and inspect before doing Step 4 batch lookup).

---

### Milestone 7 — Wishlist tab

**Build**

- New tab in the header.
- Reuses the table-rendering code with wishlist-specific columns (target, current, distance, priority, alert toggle).
- "Add to wishlist" modal — same search UX as add card, plus target_buy_price and max_pay fields.
- Distance computation + color coding.
- Header strip: total items, hot, at-or-below-target counts.

**Verify**

- Add 3 wishlist cards with various targets.
- Distance column shows correct percentages.
- One card with target above market → row highlighted as HIT.
- Refresh page → wishlist persists.

---

### Milestone 8 — Background pricing refresh

**Build**

- On dashboard open: scan `cards` for rows where `last_priced_at` is older than `refresh_interval_hours`. Queue them.
- Background fetch loop, max 2-3 concurrent requests. For Pokemon rows: try PPT (if key set) → fall back to Pokemon TCG API. For non-Pokemon: skip (they're priced only on import).
- Each successful fetch appends a row to `prices` and updates `cards.last_market_price`, `last_priced_at`, `last_price_source`.
- Failed fetches: cache the error (`last_price_error: '404 not found'`) so we don't retry for a cooldown period.
- Visible: per-row spinner during refresh, ⚠ icon if it failed; portfolio header's "Last refreshed" updates as the queue drains.
- "Refresh all now" button forces refresh regardless of cache; confirms first if it would consume >50% of remaining PPT credits.

**Verify**

- After Milestone 6 import, click "Refresh all now."
- Watch progress: maybe 30 cards out of 89 refresh (depends on PPT credit budget).
- Some prices visibly update vs the Collectr snapshot.
- Card detail panel's price history mini-chart now shows ≥2 points → real curve renders.

---

### Milestone 9 — JSON export / import (backup path)

**Build**

- "Export JSON backup" button (in settings): dumps all IndexedDB stores to a single `.json` file. Filename `vault_backup_YYYYMMDD.json`. Include version field so future imports can migrate.
- "Restore from JSON" button: file picker → parse → confirmation modal showing what would be replaced/merged → on confirm, clear existing stores and bulk-insert.
- Export includes a checkbox "Include API keys in backup?" (default off).
- "Clear all vault data" requires typing the word `DELETE` to confirm.

**Verify**

- Export → save a JSON file.
- Click "Clear all vault data," confirm.
- Open vault → empty state.
- Import the JSON file → all cards / wishlist / settings restored.

---

### Milestone 10 — Polish, edge cases, real-world test

**Build**

- Keyboard shortcuts: `/` search, `n` add card, `r` refresh all, `Esc` close panel/modal.
- Stale-price indicators (⚠ icon when `last_priced_at` is older than 2× refresh interval).
- IndexedDB-unavailable warning page (for private-mode users).
- Currency formatting throughout (USD locale).
- Empty-state copy polish.
- Loading-skeleton states during slow IndexedDB queries.
- Mobile-responsive table (table collapses to card view <700px) — stretch.

**Verify**

- Use the vault for a real session: import your CSV, refresh prices, add 1–2 wishlist items, edit a card, delete a duplicate, export a backup.
- Note any rough edges → fix the top 3.

---

## Effort estimates

Rough wall-clock time, assuming focused sessions with you available for verification at each checkpoint:

| Milestone | Effort | Notes |
|---|---|---|
| 1. Skeleton + Dexie | 1–2h | Setup + schema |
| 2. Empty state + settings | 1h | Mostly UI |
| 3. Add card manually | 2–3h | Reuses PSA search |
| 4. Main table + filters | 3–4h | Lots of UI surface |
| 5. Detail panel | 2h | |
| 6. Import wizard | 4–6h | Biggest single piece |
| 7. Wishlist tab | 1–2h | Table-reuse |
| 8. Pricing refresh | 2h | Background queue |
| 9. JSON backup | 1h | Simple |
| 10. Polish | 2–4h | Bug fixes |
| **Total** | **19–27h** | |

For working sessions in this format, that's roughly **4 to 5 sessions**:

- Session 1: Milestones 1–3 (foundation + first card)
- Session 2: Milestones 4–5 (the dashboard you'll actually use)
- Session 3: Milestone 6 (import — the longest single piece)
- Session 4: Milestones 7–9 (wishlist, refresh, backup)
- Session 5: Milestone 10 (polish + real-world test)

After Session 2, you have a usable tool — empty until you start adding cards by hand, but functional. After Session 3, your real collection is in. The remaining sessions are enrichment.

---

## Cross-cutting concerns during build

**Error handling.** Every external API call gets `try/catch`; failures are surfaced inline (not as alerts). Pricing failures don't block the UI — they just leave a stale price visible.

**Performance.** Render the table virtually (only DOM nodes for visible rows) if the user's collection grows past ~200 cards. MVP can do simple DOM rendering; Phase 1.5 adds virtualization if needed.

**Browser support.** Modern Chrome / Edge / Firefox / Safari. We use ES2020 features freely. No IE.

**Storage limits.** IndexedDB quota varies but is typically multiple GB. With ~500 cards × ~10 KB each + price history → comfortably under 10 MB total. Manual images count against the 100 MB cap we agreed on.

**Privacy.** API keys never leave the browser. Backup JSONs include them only with explicit opt-in checkbox.

**Migration discipline.** Every schema change after MVP gets a Dexie version bump + migration function. We never silently mutate existing records.

---

## What's deliberately left for *later* (not this build)

- Portfolio value chart over time (Phase 1.5)
- Set-completion view (Phase 1.5)
- Bulk-edit multi-select (Phase 1.5)
- PSA tool integration — linked decisions on card detail (Phase 2)
- Bulk PSA submission planner (Phase 2)
- Counterfactual playback (Phase 2 candidate, very valuable)
- Analytics signals — buy/sell zones, volatility flags (Phase 4)
- Cloud agent / daily digest (Phase 5)
- Google Drive sync (Phase 8)

Anything tagged Phase 1.5 is "useful, but doesn't block daily-use validation of the MVP."

---

## Risk areas to watch

**Import wizard match quality.** The Pokemon TCG API may miss some cards in your CSV (especially Japanese sets, very new sets, weird promos). The 5-unmatched estimate is a guess based on your CSV — could be higher. If match rate is <80%, we add a "fuzzy name search" pass that tries variations (strip parens, try alternate sets).

**PPT credit budget vs collection size.** Free tier is 100 credits/day. If your active collection grows past ~50 cards, the once-daily refresh exceeds the budget and we hit rate limits. Mitigation: respect the rate limit, refresh only the most stale half each day, surface "refresh limited" status in the UI. Upgrade prompt appears in settings once daily usage exceeds 80% of budget for 7 days.

**IndexedDB in private/incognito browsing.** IndexedDB exists but is wiped on tab close. Detect this on first run and warn the user.

**Re-import idempotency.** If you re-import the same Collectr CSV daily for price refresh, we must not duplicate cards. The match key `(category, tcg_id || (name+set+number), condition)` should make this robust, but the first real test will tell us if any edge cases break it.

**Schema lock-in.** Once you have data, schema changes get expensive. We've sized the schema generously (variant, grade_label, category, etc.) to absorb likely future needs without re-importing. If we miss something critical, the JSON export/import path is the migration tool.

---

## Recommended starting point

Build Milestones 1–3 in the first focused session. That gets us to "I can add one card by hand, refresh the page, and it's still there" — the smallest verifiable proof that the foundation is sound. Everything after that is layering UI on a working core.

When you're ready to start, the first thing I'll need from you is a sign-off that you've read this build plan and the design doc. Then I'll create `vault.html` and walk through Milestone 1 in the chat as I go — same iteration cadence as the PSA tool.
