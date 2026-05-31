# Pokemon Ecosystem — Session Log
*Date: May 31, 2026*

---

## Session Goals
- Fix Google Drive sync data loss issue
- Add auto-reconnect on open
- Add Push to Drive button
- Re-import card collection after data loss

---

## 1. Data Loss Incident & Root Cause

### What happened
190 cards added on Mac Studio were lost when reconnecting Drive on another
session. The vault silently imported the Drive version (5 cards) without
showing a confirmation dialog.

### Root cause
The conflict resolution logic in `driveSync()` had a fatal flaw:

```javascript
// BROKEN — old behavior
if (localCards > driveCards && localCards > 0) {
  // show confirmation dialog
} else {
  // SILENT import — no confirmation, data wiped
  await driveImportVault(data);
}
```

When `driveCards >= localCards` (even if both were 5 and local had 190 unsaved
cards from a fresh import), it imported Drive data automatically with no warning.

### Fix applied
```javascript
// FIXED — new behavior
if (localCards === 0) {
  // Safe to import silently — nothing to lose
  await driveImportVault(data);
} else {
  // ALWAYS confirm before overwriting local data
  const choice = confirm(
    `⚠️ Drive version is newer than local.\n\n` +
    `Drive: ${driveCards} cards (updated ${driveDate})\n` +
    `Local: ${localCards} cards (last synced ${localDate})\n\n` +
    `OK     → use Drive version (replaces local data)\n` +
    `Cancel → keep local version and upload it to Drive`
  );
  if (choice) { await driveImportVault(data); }
  else { await driveUpload(); } // keep local, push to Drive
}
```

**Rule now:** local data is NEVER silently overwritten unless local has 0 cards.

---

## 2. Auto-Reconnect on Open

### Problem
OAuth tokens don't persist between browser sessions. Every vault open required
manually going to Settings → Connect Google Drive. Easy to forget, causing
cards added locally to never sync.

### Fix
New checkbox in Settings → Google Drive Sync: **"Auto-reconnect on open"**

When enabled, `driveMaybeRestore()` automatically triggers the Google sign-in
popup 800ms after vault opens. User just clicks Allow once — Drive connects
and syncs immediately.

```javascript
if (s.drive_auto_reconnect) {
  setTimeout(() => driveConnect(), 800);
}
```

**Settings key added:** `drive_auto_reconnect: false` (opt-in, default off)

### Recommended setup
Enable auto-reconnect on all machines. Workflow becomes:
1. Double-click launcher → vault opens
2. Google sign-in popup appears → click Allow
3. Drive syncs automatically
4. Start working

---

## 3. Push to Drive Button

### Problem
No way to manually force an upload. If auto-sync failed or wasn't connected
during edits, there was no recovery path other than reconnecting and hoping
the conflict dialog appeared correctly.

### Fix
New **⬆ Push to Drive** button appears in Settings after connecting.
Forces an immediate upload of local vault to Drive, regardless of timestamps.

- Shown: when Drive is connected
- Hidden: when disconnected
- Wired to: `driveUpload()` directly (bypasses sync logic)

### Use cases
- After bulk import (CSV) — force push before syncing other machines
- After any major change — confirm it's on Drive before switching machines
- Whenever you're unsure if local changes are synced

---

## 4. Correct Workflow for CSV Import

When importing a large CSV batch:

1. Import CSV via 📥 Import wizard (completes locally into IndexedDB)
2. Click ⚙ Settings → Connect Google Drive
3. **If conflict dialog appears** → click **Cancel** (keep local, upload to Drive)
4. **If no dialog** → vault determined local is current → uploads automatically
5. Verify: check Drive file size or card count
6. Then sync to other machines normally

---

## 5. Recovery After Data Loss

If local data is ever lost again:

**Check Drive version history:**
1. drive.google.com → Pokemon Ecosystem folder
2. Right-click `vault_data.json` → Manage versions
3. Drive keeps 30 days of version history
4. Download an older version and restore via Settings → Restore from JSON

**In this incident:** 190 cards were re-imported from the original Collectr CSV.
Drive version history was not needed. Collection is now at 192 cards.

---

## 6. Settings Changes

New fields added to DEFAULT_SETTINGS:
```javascript
drive_auto_reconnect: false  // auto-trigger sign-in on open
```

New field added to SETTINGS_FIELD_MAP:
```javascript
's-drive-auto-reconnect': { key: 'drive_auto_reconnect', type: 'bool' }
```

---

## 7. Current Collection Status

- **Total cards:** 192 (re-imported from Collectr CSV)
- **Drive:** synced ✓ (vault_data.json updated)
- **iPhone app:** synced ✓ (192 cards visible)
- **MacBook Pro:** will sync on next connect

---

## 8. Git Commits This Session

```
Drive sync: auto-reconnect on open, Push to Drive button
Fix Drive sync: always confirm before importing, never silently overwrite local data
Fix Drive sync: always confirm before importing, auto-reconnect, Push to Drive button
```

---

## 9. Lessons Learned

- **Never auto-import without confirmation** when local has data
- **Always push after bulk operations** (CSV import, large edits)
- **Enable auto-reconnect** on all machines to prevent forgetting to sync
- **Drive version history** is a safety net — 30 days of automatic backups

---

## 10. Next Steps

- [ ] Enable auto-reconnect on MacBook Pro and Mac Mini
- [ ] Set up Mac Mini (git clone + launcher)
- [ ] Phase 6: Analytics models (Claude Code)
- [ ] Phase 7: TCGPlayer seller integration

---

*Next session: Phase 6 analytics, or TCGPlayer integration*
