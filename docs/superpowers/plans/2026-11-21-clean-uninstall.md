# Clean Uninstall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `craft-conductor uninstall` and an **Uninstall Craft Conductor…** button remove everything
Craft Conductor added, keep servers, backups, exports and launcher games unless ticked, and report
what's left to do by hand.

**Architecture:** A standard-library module `uninstall.py` holds an inventory of parts (each: find,
describe, remove, manual note) and works in two steps, `plan()` then `run()`. Every system change
goes through an injected runner so tests never touch the real computer. The command and the page
are thin layers over it.

**Tech Stack:** Python 3.11 standard library, vanilla JS under CSP, pytest, Playwright (node).

**Spec:** `docs/superpowers/specs/2026-11-21-clean-uninstall-design.md`

## Global Constraints

- Nothing is removed before the plan has been shown; servers, backups, exports, games and the
  lockbox key are kept unless ticked (`--delete-servers`, `--delete-backups`, `--delete-exports`,
  `--delete-games`, `--keep-lockbox-key` is the opposite: off means the key is deleted).
- A path is deleted only if it comes from the inventory, resolves inside a known place, isn't a link
  or junction, and isn't (or doesn't contain) the user's home folder, a drive root or a system folder.
- Order: stop servers → tunnels/Tailscale → router mappings → firewall → service → invite handler →
  games → exports → backups → servers → state → program. One failure doesn't stop the rest.
- The page action: owner only, `LOCAL_ONLY` (a browser on this computer), password re-typed; never a
  paired phone, an invited person or a tunnel visitor.
- Tests use injected runners and temporary homes; never the real registry, firewall, systemd, router,
  Tailscale or the owner's own Craft Conductor. Real runs only in disposable places (pytest temp
  homes, a WSL Docker container), and nothing touching a real router or firewall without the owner's
  approval (CLAUDE.md).
- House rules: manual section "Removing Craft Conductor", README line, `docs/headless.md`, Help if it
  covers settings, 9 translation catalogs, CHANGELOG `## 0.31.0 (not released yet)` Added, real-world
  tests (next free id, from 1066), website demo, screenshots, security then efficiency review.
- Python: `E:/craft-conductor/craft-conductor/.venv/Scripts/python.exe`; browser tests with
  `CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=E:/craft-conductor/craft-conductor/node_modules/playwright`.
  Known environmental failure: tests/test_reach.py port 8766 (the owner's own Craft Conductor).

## Review Focus

1. `CRAFT_CONDUCTOR_HOME` set to the user's home folder itself, or a server folder pointing at
   `C:\` or `/`: nothing outside Craft Conductor's own folders is deleted. (Task 1 safety tests.)
2. A backups folder that is a link to another drive, or a server folder inside the backups folder:
   no double deletion, no following the link. (Task 3.)
3. A server running with players when uninstall starts: asked first, then stopped cleanly before
   any file goes. (Task 4.)
4. The firewall prompt declined, the router unreachable, Tailscale not installed: the rest still
   happens, and each shows in the report with what to do. (Task 2.)
5. A second Craft Conductor (the panel) running on the same home while the command runs: refused
   with how to stop it. (Task 4.)

---

### Task 1: The inventory, plan and safety rules

**Files:** Create `src/craft_conductor/uninstall.py`; Test `tests/test_uninstall.py`.

**Interfaces (produced):**
- `Choices` (dataclass): `servers, backups, exports, games, keep_lockbox_key: bool = False`.
- `Part` (dataclass): `key: str`, `label: str`, `present: bool`, `action: str` (what will happen, plain
  words), `paths: list[Path]`, `manual: str | None` (what the person must do), `kept: bool`.
- `plan(home: Path, choices: Choices, *, env=None, runner=None) -> list[Part]`.
- `run(parts: list[Part], *, runner=None, progress=None) -> Report` (`Report`: `removed`, `failed`
  with why, `manual`, as lists of plain-language lines; `as_text()`).
- `safe_to_delete(path: Path, home: Path, known: list[Path]) -> bool`.
- `Runner` protocol: `run(argv: list[str], *, elevated: bool = False) -> int`, `delete_tree(path)`,
  `delete_file(path)`, `registry_delete(key)` (Windows), so tests record calls instead of acting.

- [ ] **Step 1: Failing tests:** a temp home with a fake state folder, servers, backups and exports:
  `plan` with no choices lists state as removed and servers/backups/exports as kept; ticking each
  flips only it; `safe_to_delete` refuses the user's home, a drive root, `/`, a link, a junction (on
  Windows) and anything outside `known`; `run` deletes only planned paths (assert on the fake runner's
  calls) and keeps going after a failing part, which appears in `report.failed`.
- [ ] **Step 2: Run them.** FAIL (no module).
- [ ] **Step 3: Implement** the data parts (state incl. Java and cloudflared, servers, backups (and the
  copy folder), exports, lockbox key) and the program part (frozen Windows: a detached `cmd /c`
  that waits for this process to exit, then deletes the file; frozen Linux/macOS: delete; pip/pipx
  and Docker: a manual line). Folders come from `locations.py`/hub.json and each server's config;
  read them without starting the hub.
- [ ] **Step 4: Run them.** PASS.
- [ ] **Step 5: Commit** `feat: the uninstall inventory and plan (38)`

### Task 2: System parts: router, firewall, tunnels, service, invite handler

**Files:** Modify `src/craft_conductor/uninstall.py`; Test `tests/test_uninstall.py`.

**Interfaces:** consumes Task 1's `Part`/`Runner`. Reuses `upnp` (mappings labelled `craft-conductor`,
the ports hub.json recorded), `firewall` (group "Craft Conductor"; one elevated call; `firewall
remove`'s logic), `tailscale.unserve`, the hub's cloudflared stop, `service.uninstall` (panel and
per-server units), `urlhandler` (add an `unregister()` beside `register()`).

- [ ] **Step 1: Failing tests** with the fake runner: each part present/absent per platform (monkeypatch
  `os.name`/`sys.platform`); the firewall declined → manual line with `craft-conductor firewall
  remove`; the router not found → manual line listing the ports; Tailscale missing → part absent;
  `urlhandler.unregister` removes exactly `HKCU\Software\Classes\craft-conductor` / the desktop file.
- [ ] **Step 2: Run them.** FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them.** PASS.
- [ ] **Step 5: Commit** `feat: uninstall removes the router, firewall, tunnel, service and link-handler changes (38)`

### Task 3: Launcher games

**Files:** Modify `uninstall.py` (and `join.py` / `singleplayer.py` / `launchers.py` only to read what
they recorded); Test `tests/test_uninstall.py`.

- [ ] **Step 1: Find out** how Play on this computer, single-player games and a friend's joined
  servers record what they made in each launcher (Minecraft Launcher installations and their game
  folders, Prism/MultiMC instances, Modrinth App profiles). Write it at the top of the report.
- [ ] **Step 2: Failing tests:** with `--delete-games`, only recorded installations/instances go (a
  launcher's other profiles untouched); without it, they're listed as kept; an unrecorded old install
  is listed for the person, never guessed.
- [ ] **Step 3: Implement.** **Step 4: Run.** PASS. **Step 5: Commit** `feat: uninstall can remove the games it set up in launchers (38)`

### Task 4: The command

**Files:** Modify `src/craft_conductor/cli.py` (`uninstall` subcommand); Test `tests/test_cli_uninstall.py`.

- [ ] **Step 1: Failing tests:** `craft-conductor uninstall` prints the plan and changes nothing;
  `--yes` runs it (fake runner); flags map to `Choices`; a running panel on the same home (its lock
  or port) → refused with how to stop it; servers with players → asks (or `--yes` stops them with the
  usual warning); exit code non-zero when something failed; the report text is printed and, when
  manual steps remain, saved to the Downloads folder (`folders.downloads()`).
- [ ] **Step 2: Run.** FAIL. **Step 3: Implement.** **Step 4: Run.** PASS.
- [ ] **Step 5: Real run in a disposable place:** in the WSL Docker image (e.g. `python:3.11-slim`, the
  repo copied in, a temp home with a fake server, a user systemd unit if the image allows): plan,
  `--yes`, then check the home is gone and the kept folders remain. Paste the output in the report.
- [ ] **Step 6: Commit** `feat: craft-conductor uninstall (38)`

### Task 5: The button and dialog

**Files:** Modify `src/craft_conductor/web.py` (`GET /api/hub/uninstall` → the plan; `POST
/api/hub/uninstall` with the tick boxes and the password → runs, streams progress through the
existing job/progress pattern, returns the report, then the hub exits), `access.py` (owner only),
`LOCAL_ONLY`, `src/craft_conductor/webui/app.js` (Craft Conductor settings → About & updates:
**Uninstall Craft Conductor…**), `style.css`; Tests `tests/test_web_uninstall.py`,
`tests/ui_uninstall.cjs` + `tests/test_ui_uninstall.py`.

- [ ] **Step 1: Failing tests:** an invited person, a paired phone and a request from another computer
  get refused (403/404 as the existing LOCAL_ONLY routes do); a wrong password is refused; the GET
  plan matches `uninstall.plan`; the POST passes only the tick boxes (no paths accepted from the
  request). Browser test: the dialog lists the plan with all boxes off, ticking **Delete my servers
  and worlds** asks a second confirmation naming the count, **Uninstall** shows progress and then the
  report, which stays on the page after the server has gone (fake runner in the test hub).
- [ ] **Step 2: Run.** FAIL. **Step 3: Implement.** **Step 4: Run.** PASS.
- [ ] **Step 5: Commit** `feat: Uninstall Craft Conductor in Craft Conductor settings (38)`

### Task 6: Docs, translations, demo, real-world tests, screenshots

- [ ] Manual section **Removing Craft Conductor** (what goes, what's kept, the lockbox warning, the
  command, what to do by hand), README one line, `docs/headless.md` row, Help if it covers settings,
  CHANGELOG Added, 9 catalogs for every new page string, website demo (a simulated dialog that shows a
  plan and a fake report, removing nothing; `tests/test_website_demo_contract.py` passes), real-world
  tests from id 1066 (Windows portable exe with firewall rules and UPnP on a disposable PC; Linux user
  service; Linux system service; pipx; Docker; keep-everything vs delete-everything; the lockbox
  warning), screenshot of the dialog (`tests/test_screenshots.py`, keep only the new/changed pictures),
  full suite, commit `docs: removing Craft Conductor in the manual, help and tests (38)`.

Then: the final whole-branch review (security first), push, a DRAFT PR "not to be merged until the
release candidate is out", ending with the Claude Code line. Never merge.
