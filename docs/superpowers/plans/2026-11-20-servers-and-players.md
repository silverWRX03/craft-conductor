# Servers and players (51, 50, 37) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recent servers in the left panel, a custom server icon, and a Discord webhook help link.

**Architecture:** The hub's server summary (`Hub.summary`) gains `last_started`, `last_played` and
`icon`; the page sorts and shows the recent list. A new `servericon.py` checks and stores
`server-icon.png`; three per-server routes expose it. The webhook link is page-only.

**Tech Stack:** Python 3.11+ standard library; vanilla JS under CSP `script-src 'self'`; pytest.

**Spec:** `docs/superpowers/specs/2026-11-20-servers-and-players-design.md`

## Global Constraints

- Standard library only at runtime (no image library).
- No inline scripts, no new script/image origins (CSP unchanged).
- Every new route is in `access.SERVER_ROUTES` (`tests/test_access.py` checks it).
- Every new page string has an entry in each `webui/i18n/*.json` (es, pt, fr, de, hi, zh, vi, ar, ko).
- Manual (`webui/manual.md`), Help (`HELP` in `app.js`), CHANGELOG under `## 0.31.0 (not released yet)`.
- Real-world tests via `python tools/real_world_tests.py add-test --section "Feature: …" --type Extra`.

## Review Focus

- A non-PNG, a PNG of another size, a huge body, or a PNG with a bad IHDR CRC sent straight to the API: refused (400/413), `server-icon.png` unchanged. (Task 2 tests.)
- An invited person without `settings.safe` posting an icon: 403; without a grant on the server: 404. (Task 2 tests.)
- `hub.json` holding a damaged `started` value (`"started": 5`): ignored, no crash. (Task 1 test.)
- A server deleted after it was started: its `started` entry no longer listed. (Task 1 test.)
- The recent list for a person who sees only one server: hidden. (Task 3, JS sort is pure: tested via node in the UI test or by reasoning; `recentServers` exported for tests.)

---

### Task 1: last started / last played in the server summary

**Files:**
- Modify: `src/craft_conductor/hub.py` (`HUB_FILE_KINDS`, `after_ready`, `summary`, server removal)
- Modify: `src/craft_conductor/activity.py` (new `last_played`)
- Test: `tests/test_recent_servers.py`

**Interfaces:**
- Produces: `Activity.last_played(now: float | None = None) -> float | None` (now when someone is on; else the latest visit's end; None with no visits; reads the file at most once per change, cached by stat).
- Produces: `Hub.summary()` items gain `"last_started": float | None` and `"last_played": float | None`; hub.json key `"started": {sid: float}`.

- [ ] Tests: `test_last_played_is_now_while_online`, `test_last_played_from_file`, `test_last_played_none_without_visits`, `test_ready_records_last_started` (calling `hub.after_ready(daemon)` stores time; summary shows it), `test_damaged_started_is_ignored`, `test_removed_server_forgets_started`.
- [ ] Run, see them fail. Implement. Run `pytest -q tests/test_recent_servers.py tests/test_hub.py tests/test_activity.py`, pass. Commit.

### Task 2: server icon (module + routes)

**Files:**
- Create: `src/craft_conductor/servericon.py`
- Modify: `src/craft_conductor/web.py` (routes `GET /api/server-icon`, `POST /api/server-icon`, `POST /api/server-icon/remove`; `GET` served as `image/png`, `Cache-Control: private, max-age=86400`, 404 when none)
- Modify: `src/craft_conductor/access.py` (GET: `status.view`; both POSTs: `settings.safe`)
- Modify: `src/craft_conductor/hub.py` (`summary` item `"icon": int | None`: the file's mtime_ns // 1e6, for `?v=`)
- Test: `tests/test_server_icon.py`

**Interfaces:**
- Produces: `servericon.FILE = "server-icon.png"`, `MAX_BYTES = 64 * 1024`, `check(data: bytes) -> None` (ValueError with a plain message), `save(server_dir: Path, data: bytes) -> None` (check then tmp + `os.replace`), `remove(server_dir: Path) -> bool`, `stamp(server_dir: Path) -> int | None`.
- POST body: `{"png": "<base64>"}` (fits `MAX_JSON`).

- [ ] Tests: valid 64×64 PNG saved; 32×32 refused ("must be 64 × 64"); not a PNG refused; bad IHDR CRC refused; > MAX_BYTES refused; bad base64 refused (400); remove deletes and is idempotent; GET 404 then 200 image/png; viewer gets 403 on POST, a person without a grant 404; summary `icon` changes after save.
- [ ] Run, fail, implement, pass (`pytest -q tests/test_server_icon.py tests/test_access.py`). Commit.

### Task 3: the page (recent list, icon card, server card picture, webhook link)

**Files:**
- Modify: `src/craft_conductor/webui/app.js` (`recentServers(servers)`, `renderNav` Recent group, Settings `Server icon` card, server card `<img>`, webhook link)
- Modify: `src/craft_conductor/webui/style.css` (nav recent rows, icon preview 64px pixelated)
- Modify: `webui/i18n/*.json`
- Test: `tests/test_ui_recent_and_icon.py` + `tests/ui_recent_and_icon.cjs` (pattern of `test_ui_bell.py`)

**Interfaces:**
- Consumes: Task 1/2 summary fields and routes.
- `recentServers(servers) -> servers[]`: drop `unavailable` and `setup_pending`; running first by `last_played` desc (null last), then others by `last_started` desc, never-started last by name; first 3. Empty when fewer than 2 visible servers or `hb.single`.
- Nav link: same view on the other server if `SERVER_VIEWS` has it and `canView` for that server, else dashboard.
- Icon card: canvas `drawImage` into 64×64, `toDataURL("image/png")`, strip prefix, POST; preview `<img src=scoped("/api/server-icon")+"?v="+icon>`; "Minecraft shows it from the next restart."; shown when `can("settings.safe")`.
- Webhook link: `https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks` (checked before adding), text "How to make a webhook ↗".

- [ ] UI test: nav shows Recent with up to 3 in the expected order, hidden with one server; picking a server keeps the view; Settings shows the icon card and the webhook link. Run, fail, implement, pass. `pytest -q tests/test_webui_syntax.py tests/test_i18n.py`. Commit.

### Task 4: help, changelog, real-world tests, screenshots, TODO

- [ ] `manual.md` (left panel Recent; Settings → Server icon; webhook link), `HELP` entries if the settings page is covered there.
- [ ] CHANGELOG `## 0.31.0 (not released yet)` Added lines.
- [ ] `real_world_tests.py add-test` ×3 (sections "Feature: recent servers in the left panel", "Feature: custom server icon", "Feature: Discord webhook help link").
- [ ] Retake affected screenshots (`tests/test_screenshots.py`), if the environment can.
- [ ] TODO.md: tick 37, 50, 51 and 56.
- [ ] Full `pytest -q`. Commit.

### Task 5: security then efficiency review, PR

- [ ] Security: icon routes (size before decode, auth, path fixed, no symlink follow outside the server dir), nav links built from ids only. Efficiency: `last_played` cached; summary adds one `stat` per server.
- [ ] Push, open PR, CI green.
