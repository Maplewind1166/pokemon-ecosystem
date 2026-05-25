# Pokemon Ecosystem — Session Log
*Date: May 24, 2026*

---

## Session Goals
- Establish full project infrastructure (GitHub, Google Drive, Obsidian)
- Fix vault.html bugs blocking real use
- Prepare for Phase 2 (PSA tool integration)

---

## 1. Infrastructure Setup

### GitHub
- Repo created: `https://github.com/Maplewind1166/pokemon-ecosystem` (private)
- Local folder: `~/pokemon-ecosystem/`
- Structure:
  ```
  pokemon-ecosystem/
  ├── desktop/    ← vault.html, psa_decision_tool.html, PSA_Decision_Workbook.xlsx, price_lookup.py, HOW_TO_USE.md
  ├── app/        ← PWA mobile app (Phase 5, empty)
  ├── agent/      ← Python cloud agent (Phase 4, empty)
  ├── analytics/  ← ML models (Phase 6, empty)
  ├── docs/       ← SUITE_DESIGN.md, VAULT_BUILD_PLAN.md, VAULT_MVP_DESIGN.md
  └── .github/
      └── workflows/  ← GitHub Actions cron (Phase 4, empty)
  ```
- `.gitignore` protects `.env` and `PokemonPriceAPI.txt`
- API key stored in `~/pokemon-ecosystem/.env` (never committed)

### Google Drive
- Folder: `My Drive/Pokemon Ecosystem/`
- Subfolder: `My Drive/Pokemon Ecosystem/backups/`
- `vault_data.json` uploaded to top level (4 cards at time of export)
- Live master file always at top level; dated backups go in `backups/`

### Obsidian
- Note created: `Obsidian-Business/Pokemon-TCG/00 Ecosystem Overview.md`
- Links to GitHub repo, Google Drive folder, local file path
- Phase status tracker embedded in note
- Connection to WindSaga11 documented (shared via Drive JSON, no code integration)

---

## 2. Key Architectural Decisions

### WindSaga11 vs Pokemon Ecosystem
- **Separate repos** — different tech stacks (Streamlit vs HTML), different scopes
- **Shared data spine** — both read/write Google Drive JSON files
- **Connection point** — WindSaga11 Business Panel (Phase 3, Priority 3) will read
  `vault_data.json` and `signals.json` from Drive; no code integration needed
- WindSaga11 repo: `https://github.com/Maplewind1166/WindSaga11`

### Obsidian vault assignment
- Pokemon tools → `Obsidian-Business` vault, `Pokemon-TCG/` folder (already existed)
- Do NOT create a new category — use existing structure

### How to run vault locally (always use this, never double-click)
```bash
cd ~/pokemon-ecosystem/desktop
python -m http.server 8000
# then open http://localhost:8000/vault.html
```

---

## 3. Vault Fixes Applied

### Root cause discovered
PPT (PokemonPriceTracker) API blocks browser requests via CORS. The `Authorization`
header triggers a preflight request that PPT's server rejects. This silently broke
all PPT calls in the vault — price refresh, search, portfolio history, wishlist pricing.
Python scripts (price_lookup.py) were unaffected because they don't send preflights.

### Fix 1: CORS Proxy for all PPT calls
**Problem:** Browser cannot call PPT API directly (CORS preflight blocked).  
**Solution:** Route all PPT calls through `corsproxy.io`.  
**Implementation:** Added `CORS_PROXY` constant and `pptFetch()` helper function.
All 5 PPT fetch call sites updated to use `pptFetch()` or `CORS_PROXY`.

```javascript
const CORS_PROXY = 'https://corsproxy.io/?';

async function pptFetch(endpoint, key) {
  const fullUrl = PPT_BASE + endpoint;
  const proxied = CORS_PROXY + encodeURIComponent(fullUrl);
  return fetch(proxied, { headers: { Authorization: `Bearer ${key}` } });
}
```

**Locations updated:**
- `searchPokemonPriceTracker()` — card search
- `refreshSingleCardPrice()` — single card price refresh
- Portfolio history fetch (line ~4065)
- Wishlist price refresh (line ~4451)

### Fix 2: normalizePpt() field mapping
**Problem:** PPT API v2 returns different field names than the vault expected.  
**Old code looked for:** `c.set.name`, `c.number`, `c.imageUrl`  
**PPT actually returns:** `c.setName`, `c.cardNumber`, `c.imageCdnUrl200`  
**Fix:** Updated `normalizePpt()` to read correct fields with proper fallback chain:

```javascript
const setName = c.setName ?? c.set?.name ?? (typeof c.set === 'string' ? c.set : '') ?? '';
const number = c.cardNumber ?? c.number ?? '';
const image = c.imageCdnUrl200 ?? c.imageCdnUrl400 ?? c.imageUrl ?? c.image?.small ?? '';
const imageLarge = c.imageCdnUrl800 ?? c.imageCdnUrl400 ?? c.imageLarge ?? image;
```

Also added `pptId` field to normalized output:
```javascript
pptId: c.id ?? null,
```

### Fix 3: Promo card search (name-only PPT search)
**Problem:** PPT search was called with `"Mega Charizard X ex 023"` — appending
the card number confused PPT's search engine and returned wrong/no results.  
**Fix:** Search PPT by name only. If a number is provided, sort exact matches
to the top of results instead of filtering.

```javascript
// Before: search = name + ' ' + number
// After: search = name only; number used for sorting
const params = new URLSearchParams({ search: name.trim(), limit: '24' });
// Then sort exact number matches to top:
normalized.sort((a, b) => {
  const aMatch = a.number && a.number.replace(/^0+/, '') === n ? 0 : 1;
  const bMatch = b.number && b.number.replace(/^0+/, '') === n ? 0 : 1;
  return aMatch - bMatch;
});
```

### Fix 4: Deduplication by tcgPlayerId
**Problem:** Dedup used `name|number|set` string matching. PPT and TCG API use
different set name formats (e.g. `"Scarlet & Violet—Obsidian Flames"` vs
`"Obsidian Flames"`), causing duplicates for cards found in both APIs.  
**Fix:** Deduplicate by `tcgPlayerId` (shared between both APIs) with
`name|number` as fallback for cards without a tcgPlayerId.

```javascript
const seen = new Set(combined.map(c =>
  c.tcgPlayerId ? `id:${c.tcgPlayerId}` : `${c.name}|${c.number}`.toLowerCase()
));
r.forEach(c => {
  const k = c.tcgPlayerId ? `id:${c.tcgPlayerId}` : `${c.name}|${c.number}`.toLowerCase();
  if (!seen.has(k)) { seen.add(k); combined.push(c); }
});
```

Applied in two locations: Add Card search and Wishlist search.

### Fix 5: ppt_id stored in card record
**Problem:** PPT-only cards (promos) have no `tcg_id`. Without storing PPT's own
ID, price refresh had no way to look them up later.  
**Fix:** `ppt_id` now stored in card identity and card record when saving a
PPT-sourced card.

```javascript
// In identity object:
ppt_id: s.source === 'ppt' ? (s.pptId || null) : null,

// In card record:
ppt_id: identity.ppt_id || null,
```

### Fix 6: Price refresh supports ppt_id
**Problem:** `refreshSingleCardPrice()` returned early with error if no `tcg_id`,
blocking refresh for all promo cards.  
**Fix:** Function now checks for either `tcg_id` or `ppt_id`. Uses PPT's `id`
endpoint for promo cards, `tcgPlayerId` endpoint for regular cards.

```javascript
// Before: if (!card.tcg_id) return { error: 'No tcg_id' };
// After:
if (!card.tcg_id && !card.ppt_id) return { error: 'No price ID — relink via Add Card search' };

const pptEndpoint = card.ppt_id
  ? `/cards?id=${encodeURIComponent(card.ppt_id)}&limit=1`
  : `/cards?tcgPlayerId=${encodeURIComponent(card.tcg_id)}&limit=1`;
const r = await pptFetch(pptEndpoint, key);
```

### Fix 7: Refresh button enabled for ppt_id cards
**Problem:** Detail panel refresh button was disabled for cards without `tcg_id`.  
**Fix:** Button now enables for cards with either `tcg_id` or `ppt_id`.

```javascript
// Before: if (card.category === 'Pokemon' && card.tcg_id)
// After:
if (card.category === 'Pokemon' && (card.tcg_id || card.ppt_id))
```

---

## 4. Important Operational Notes

### PPT API key must be saved in vault settings
The PPT API key is stored in browser IndexedDB, not the code. Must be entered
manually in ⚙ Settings → PokemonPriceTracker API Key after any browser/machine change.

**Current key:** `pokeprice_free_e59ae7774acb3da38410ee3ada1ad6bd0d18be4aeb29ccb9`  
**Free tier limit:** 100 credits/day. Resets at midnight.  
**Credit cost:** ~1 credit per card search result returned (limit=24 costs up to 24 credits).

### PPT credit limit behavior
When credits are exhausted, PPT returns HTTP 429. The vault catches this and
falls back to TCG API only — promo cards disappear from search results silently.
This is expected behavior. Wait for midnight reset.

### TCGPlayer API: closed to new applicants
TCGPlayer closed new API applications permanently. Not an option for future
integration. Use PPT as the primary pricing source.

### corsproxy.io dependency
The vault now depends on `corsproxy.io` for all PPT calls. If this proxy goes
down, PPT calls will fail silently and fall back to TCG API only. Future
mitigation: Phase 4 agent runs server-side Python (no CORS issue) and writes
prices to Drive JSON, reducing browser→PPT call frequency.

---

## 5. Pending Items

### To verify next session
- [ ] Confirm Mega Charizard X ex 023 appears in search (PPT credits reset overnight)
- [ ] Add 023 promo to vault and verify price refresh works

### Phase 2: PSA Tool Integration (next build)
- Merge `psa_decision_tool.html` as a tab inside `vault.html`
- "Evaluate for PSA" button in card detail panel → pre-fills PSA tab
- PSA decisions stored in vault IndexedDB, linked by `card_id`
- Settings consolidated into vault's settings panel
- Bulk submission planner (optimize batch PSA submissions)

### UI Improvements (noted, deferred)
- Better card display layout
- Improved search results presentation
- General polish after functionality is complete

### Phase 3: Google Drive Sync
- OAuth button in vault settings
- Auto-sync on save (debounced)
- Eliminates need to manually export/import JSON between machines

---

## 6. Git Commit History (this session)

```
Initial commit: vault, PSA tool, design docs
Add .gitignore with .env and API key protection
Fix PPT: CORS proxy, promo support, deduplication, ppt_id storage
Fix deduplication: use tcgPlayerId instead of set name string
```

---

*Next session: verify promo fix → begin Phase 2 PSA integration*
