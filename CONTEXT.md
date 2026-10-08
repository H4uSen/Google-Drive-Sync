# Obsidian Google Drive Sync

A desktop app that keeps local Obsidian vaults in two-way sync with folders on Google Drive.

## Language

**Vault**:
One local folder paired with one Google Drive folder, synced as a unit. A user can have several; exactly one is active.
_Avoid_: profile, vault profile, workspace

**Sync run**:
One bisync pass between a Vault's local folder and its Drive folder. A retry after clearing a stale lock is a second Sync run.
_Avoid_: sync, job, batch, execution

**Resync**:
A Sync run that rebuilds the baseline of both sides from scratch instead of comparing against the last run. Required for a Vault's first Sync run and after a safety stop.
_Avoid_: repair, reset, full sync

**Sync engine**:
The background loop that decides when the active Vault gets a Sync run: on a timer, on a Watcher signal, or on user request.
_Avoid_: worker, daemon, scheduler

**Watcher**:
The observer of a Vault's local folder that asks the Sync engine for a Sync run when files change.
_Avoid_: file monitor, listener
