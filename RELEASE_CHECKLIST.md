# NYXUS AI Release Checklist

Run through this before cutting any release, not just v1.0.0 — it's meant to
be reused, not a one-off.

## 1. Version consistency

- [ ] `memoryos/__version__.py`'s `__version__` matches `packaging/memoryos.iss`'s `#define MyAppVersion` (these are two manually-synced hardcoded values, not a shared source of truth — see the cross-referencing comments in each file).
- [ ] Help > About NYXUS AI in the running app shows the correct version.
- [ ] `packaging/memoryos.iss`'s `OutputBaseFilename` (`NyxusAI-Setup-{version}`) matches.

## 2. Automated tests

- [ ] `.venv\Scripts\python -m pytest tests/` — full suite green, zero skipped/xfailed without a documented reason.

## 3. Fresh packaging build

- [ ] Rebuild the frozen app from the *current* source tree (`pyinstaller packaging/memoryos.spec --noconfirm`) — don't reuse a `dist/NyxusAI` built before the latest code changes.
- [ ] Rebuild the installer from that fresh frozen app (`ISCC.exe packaging/memoryos.iss`).
- [ ] If building on this machine: use `--distpath`/`--workpath` outside any OneDrive-synced folder (a known file-lock issue during in-place rebuilds — see `memoryos_poc_status` notes) and `MSYS_NO_PATHCONV=1` for any Git-Bash-driven silent install/uninstall commands.

## 4. Manual regression (fresh installed build)

- [ ] Silent install to a scratch directory; confirm the installed folder structure matches `dist/NyxusAI` (exe, `_internal`, bundled icons/styles/model_cache all present).
- [ ] Launch the installed exe; confirm it starts and stays alive with **no visible console window**.
- [ ] Start Menu shortcut present; optional Desktop shortcut only appears if that install-time task was checked.
- [ ] Add/Remove Programs entry shows the correct name/version/publisher/icon.
- [ ] Real indexing run: pick a real folder, index it, confirm 0 unexpected errors, confirm Pause/Resume/Cancel all work.
- [ ] Real search: a few queries return correct, sensible top results.
- [ ] File actions (Open, Reveal in Folder, Copy Path, Rename, Delete) all work from a result card.
- [ ] Theme switching (Light/Dark/System) works and persists across a relaunch.
- [ ] Deliberately trigger an exception (e.g. point at a folder path that will fail partway) and confirm `%APPDATA%\MemoryOS\crash.log` actually captures a traceback — a windowed build with broken crash logging fails *silently*, which is worse than not having windowed mode at all.
- [ ] Silent uninstall; confirm the install directory, shortcuts, and Add/Remove Programs entry are all gone, and `%APPDATA%\MemoryOS` (the index/history data) is still present.
- [ ] **Manual/interactive-only** (no native GUI automation tool available to Claude in these sessions): double-click launch the installed exe once, confirm it *looks* right with no console window, and double-click-run the uninstaller once (not silently) to see the actual data-deletion checkbox and confirm data really is removed if you explicitly check it.

## 5. Licenses & docs

- [ ] `THIRD_PARTY_LICENSES.md` covers every bundled third-party asset (currently: Fluent UI System Icons, MIT).
- [ ] `README.md` accurately describes the current feature set and both run paths (from source, via installer).
- [ ] `PERFORMANCE_BASELINE.md` is current if indexing/search performance changed materially since it was last written.

## 6. Known, disclosed limitations (confirm these are still accurately described, not silently "fixed and forgotten to update")

- [ ] No code-signing certificate — SmartScreen "unknown publisher" warning on both the installer and the frozen exe.
- [ ] Battery-saver/fullscreen auto-pause detection is only mock-tested (`tests/test_resource_monitor.py`), never validated on real battery-powered/fullscreen hardware.
- [ ] The legacy CLI + JSON/NumPy `IndexStore` path (`memoryos/index/store.py`, `memoryos/cli/`) is still present as a deferred-retirement fallback, not part of the supported release path.
