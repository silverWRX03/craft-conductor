# Mods and Modpacks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skip the load check for a modpack's own mods, show a progress bar while a server is made, and
make a modpack (.mrpack or CurseForge .zip) from a server's mods.

**Architecture:**
- **Load check (54):** a filter in `filecheck.check` (`ignore=`) for the setup page, and a matching
  filter in `Manager.mod_problems` for the install. Both decide "the pack's own" from the same
  pack keys and files.
- **Progress (49):** a `Manager.progress` callback that `Daemon.run_setup` turns into
  `job["progress"]`, drawn by the setup page.
- **Make a modpack (53):** a new standard-library module `makepack.py` that builds either format from
  the lock and `clientpack.players_mods`, sent by the request handler.

**Tech Stack:** Python 3.11 standard library, vanilla JS under CSP, pytest, Playwright (node) for
browser tests.

**Spec:** `docs/superpowers/specs/2026-11-20-mods-and-modpacks-design.md`

## Global Constraints

- Standard library only at runtime. No inline scripts or styles that break `script-src 'self'`.
- Names: `craft-conductor` / `craft_conductor` / `CRAFT_CONDUCTOR_*`.
- Every user-visible string goes through `t()` in the page, with a translation in all 9 catalogs
  (`webui/i18n/{es,pt,fr,de,hi,zh,vi,ar,ko}.json`, `json.dumps(ensure_ascii=False, indent=2)`).
- The manual (`webui/manual.md`), Help (`HELP` in app.js) where it covers it, and CHANGELOG under
  `## 0.31.0 (not released yet)` (Added/Changed).
- Real-world tests via `python tools/real_world_tests.py add-test`.
- `pytest -q` passes. Run it with `../craft-conductor/.venv/Scripts/python.exe -m pytest`.
- Browser tests use `CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=E:/craft-conductor/craft-conductor/node_modules/playwright`.
- **A made modpack:**
  - Holds no jar files: links to `cdn.modrinth.com` only (`.mrpack`), or CurseForge project and file
    ids only.
  - Holds no config files.
  - Names every mod left out, with why.

## Review Focus

1. A pack mod whose dependency the person removed in setup (`modpack_exclude`): the "missing"
   problem must still be shown, at setup and at install.
2. A pack mod held at another file than the pack's (changed in Manage Mods since): its problems
   count, at install.
3. **A made modpack from a server with:**
   - mods from both sites;
   - a hand-added jar;
   - a datapack;
   - a players-only mod;
   - an optional mod.

   Each lands in the right place, or in `left_out`, with the right `env`.
4. A server name with characters that aren't allowed in a file name, or quotes: the download's
   file name is safe, and the header can't be broken.
5. A setup that fails or is stopped halfway: `Manager.progress` is cleared, and a later update of
   the same server reports nothing.

---

### Task 1: The setup check skips the pack's own mods

**Files:**
- Modify: `src/craft_conductor/filecheck.py` (`check`, `for_server`, `for_setup`, `_pack_part`)
- Modify: `src/craft_conductor/webui/app.js` (`setupCheckShown` / the create box: the pack-only note)
- Test: `tests/test_pack_load_check.py` (new)

**Interfaces:**
- Produces:
  - `filecheck.pack_own(problem: dict, pack_keys: set[str], excluded: bool) -> bool`.
  - `filecheck.check(..., ignore: Callable[[dict], bool] | None = None)`: a problem dict for which
    `ignore` is true is dropped before fixes are looked for.
  - `for_server(..., ignore=None)` passes it on.
- `for_setup` returns `{"ok": True, "problems": [], "unreadable": [], "pack_only": True}` at once when
  `spec.modpack_version` is set and `spec.mods`, `spec.optional_mods` and `spec.client_mods` are all
  empty.

- [ ] **Step 1: Write the failing tests** in `tests/test_pack_load_check.py`.
  - Helpers: a pack built like `test_pack_update.build`/`publish`, but with `content=` fabric jars
    from `test_modcheck.fabric`.
  - `PACKMOD` is `fabric("packmod", "1.0", {"missingthing": "*"})`: a pack mod that needs a mod no
    one has.
  - `ADDED` is `fabric("added", "1.0", {"alsomissing": "*"})`, published as Modrinth project `ADDED`.
  - `test_pack_only_setup_check_answers_at_once(hub_env, http, modrinth)`: POST
    `/api/hub/mods/filecheck` with `modpack_version` set and no mods. Then
    `result == {"ok": True, "problems": [], "unreadable": [], "pack_only": True}`, and the pack's
    mod file URL is not in `http.downloads`.
  - `test_the_packs_own_problems_are_skipped_but_added_mods_are_checked(hub_env, http, modrinth)`:
    the same pack plus `mods: ["added"]`. Then `[p["mod"] for p in result["problems"]] == ["added"]`.
  - `test_a_removed_pack_mod_keeps_missing_problems(hub_env, http, modrinth)`:
    - A pack with `PACKMOD` and a second mod `CUT`.
    - `modpack_exclude=[CUT's path]` and `mods: ["added"]`.
    - Then both "packmod" and "added" problems are there.
  - `test_pack_own_rule`: unit test of `pack_own`:
    - complainer in the pack, `needs_key` None, `excluded` False → True;
    - `needs_key` not in the pack → False;
    - complainer not in the pack → False;
    - `kind` "missing" with `excluded` True → False;
    - `kind` "minecraft" with `excluded` True → True.

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tests/test_pack_load_check.py -q`
Expected: FAIL (`pack_own` doesn't exist; problems include "packmod"; no `pack_only`).

- [ ] **Step 3: Implement.**
  - `pack_own`: true when `problem["key"]` is in `pack_keys`, and `needs_key` is None or in
    `pack_keys`, unless `kind == "missing"` and `excluded`.
  - **Pack keys in `for_setup`:**
    - `{s.label for s in pack_specs}`;
    - `| {f"local:{p.name}" for p in pack_jars}`;
    - `| set(pack_client)` (normalised to "source:id" form);
    - then minus the keys of mods the person picked themselves (`spec.mods`, `optional_mods` and
      `client_mods` resolved the way the planner names them; a key both picked and in the pack
      counts as the pack's).
  - Pass `ignore=lambda p: pack_own(p, keys, bool(spec.modpack_exclude))` through `for_server`.

- [ ] **Step 4: The page.** When the check result has `pack_only`, the create box shows
  `t("The modpack's own mods aren't checked: its maker did that.")` as a muted small line.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_pack_load_check.py tests/test_mod_checks_web.py -q`
Expected: PASS

- [ ] **Step 6: Commit** `feat: the setup check skips a modpack's own mods (54)`

### Task 2: The install doesn't stop on the pack's own problems

**Files:**
- Modify: `src/craft_conductor/packupdate.py` (new `pack_files`)
- Modify: `src/craft_conductor/manager.py` (`mod_problems`)
- Test: `tests/test_pack_load_check.py`

**Interfaces:**
- Produces: `packupdate.pack_files(root: Path, plan_mods: list[ModFile], mods_dir: Path) -> tuple[set[str], bool]`.
  - It returns the jar file names that are the pack's own, and whether mods were left out of the
    pack (`state["removed"]` not empty).
  - **The pack's own files:**
    - each `mod.filename` in `plan_mods` whose `state["mods"].get(mod.key) == mod.version_id`;
    - plus each `state["files"]` path under `mods/` ending `.jar` whose file in `mods_dir` still has
      that SHA-1.
  - A server not made from a pack returns `(set(), False)`.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_pack_server_installs_despite_its_own_problems(make_config, http, modrinth)`:
    - `modpack.apply(cfg.root, PACKV, http)` with a pack holding `PACKMOD`.
    - `update(manager(...)).ok` is True, and `m.lock.installed`.
  - `test_an_added_mods_problem_still_stops_the_install(...)`: the same, plus
    `configmod.append_mod(cfg.path, ModSpec("modrinth", "ADDED"))`. Then `update` is not ok, and
    "added" is in the message.
  - `test_a_pack_mod_on_another_file_is_checked(...)`: the pack applied, then the pin of PACKMOD
    changed to a second published build `PACKMOD-2.0` with the same missing dependency. Then
    `update` is not ok.
  - `test_pack_files_without_a_pack(tmp_path)`: returns `(set(), False)`.

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tests/test_pack_load_check.py -q -k "install or file or pack_files"`
Expected: FAIL (the update is refused with "wouldn't start together").

- [ ] **Step 3: Implement.**
  - Write `pack_files`.
  - In `mod_problems`, after `modcheck.check`, drop each problem where:
    - `problem.file` is in the pack's files, and
    - the mod it needs is given only by pack files, or by none (map `id`/`provides` →
      `ModInfo.file` over `mods`),
    - unless `kind == "missing"` and mods were left out.

- [ ] **Step 4: Run them**

Run: `python -m pytest tests/test_pack_load_check.py tests/test_modcheck.py tests/test_pack_update.py -q`
Expected: PASS

- [ ] **Step 5: Commit** `feat: an install isn't stopped by a modpack's own mods (54)`

### Task 3: Progress while a server is made

**Files:**
- Modify: `src/craft_conductor/manager.py` (`__init__`: `self.progress = None`; `stage`; `apply`)
- Modify: `src/craft_conductor/daemon.py` (`run_setup`)
- Modify: `src/craft_conductor/webui/app.js` (`renderProgress`; a new pure `setupSteps(progress)`)
- Modify: `src/craft_conductor/webui/style.css`
- Test: `tests/test_setup_progress.py` (new), `tests/ui_mods_and_packs.cjs` +
  `tests/test_ui_mods_and_packs.py` (new; Task 5 adds to them)

**Interfaces:**
- **`Manager.progress`:** `Callable[[str, int | None, int | None], None] | None`. Calls, in order:
  - `("java", None, None)` before `java.select`;
  - `("mods", 0, n)`, then `("mods", i, n)` after each mod in `stage`;
  - `("runtime", None, None)` before `loader.install` (only when `changes.runtime`);
  - `("boot", None, None)` before the test boot in `apply` (only when `will_boot`).
  - Errors from the callback are logged and ignored.
- **`job["progress"]`:** `{"steps": [...], "step": str, "done": int | None, "total": int | None}`.
  - Steps from `("pack", "plan", "manual", "java", "mods", "runtime", "boot")`.
  - `pack` only with a modpack. `manual` only once waiting for hand downloads. `mods` dropped when
    `("mods", 0, 0)` arrives.
- **JS:**
  - `SETUP_STEP_TEXT`: the step key → English text, from the spec.
  - `setupSteps(progress) -> {items: [{key, text, state: "done"|"now"|"later"}], value: number (0..1), label: string}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_setup_progress.py`.
  - `test_the_manager_reports_each_step(make_config, http, modrinth)`:
    - Two mods; `m.progress = lambda *a: seen.append(a)`; `update(m)`.
    - Then `seen` starts `("java", None, None)` and contains `("mods", 0, 2)`, `("mods", 2, 2)`,
      `("runtime", None, None)`, `("boot", None, None)`, in that order.
  - `test_a_broken_progress_callback_doesnt_stop_the_install(...)`: a callback that raises; `update`
    is still ok.
  - `test_setup_records_progress_in_the_job(hub_env, ...)`:
    - Create a server through `/api/hub/create` with a mod.
    - Poll `/api/servers/<id>/status` (or the hub summary) until `job.progress` is seen; collect the
      steps seen.
    - `progress["steps"][0] == "plan"`, and `"boot"` is reached.
    - After the job ends, the daemon's `m.progress is None`.
  - `test_a_failed_setup_clears_the_progress_callback`: a setup whose mod can't be found fails, and
    the daemon's `m.progress is None` afterwards.

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tests/test_setup_progress.py -q`
Expected: FAIL (`progress` isn't called; no `job["progress"]`).

- [ ] **Step 3: Implement** the Manager calls (a `_report(step, done=None, total=None)` helper that
  swallows and logs exceptions), and `run_setup`:
  - Steps list built first.
  - `self._progress(step, done, total)` updates `self.job["progress"]` when `self.job` is a dict.
  - `pack` reported before the pack is applied; `plan` before `check_only`; `manual` (inserted
    before `java`) before `wait_for_manual_downloads`.
  - `self.m.progress` is set at the start and cleared in a `finally`.

- [ ] **Step 4: The page.**
  - `renderProgress` gets an `<ol class="setup-steps">` and a `<progress max="1">` with
    `aria-valuetext`, refreshed in its existing `every(1500)` loop from `status.job.progress`
    (`refill` by a key, so it isn't redrawn needlessly).
  - **The bar's value** = (steps before the current one + (`done/total` when `total`)) / number of
    steps.
  - `label` = the current step's text, plus `: {done} of {total}` when `total`.
  - Under `lessMotion()`, or with `prefers-reduced-motion`, the bar doesn't animate (CSS).

- [ ] **Step 5: The browser test** `tests/ui_mods_and_packs.cjs` (run by
  `tests/test_ui_mods_and_packs.py` the same way `test_ui_recent_and_icon.py` runs its script).
  It checks with `page.evaluate(() => setupSteps({...}))`:
  - `{steps: ["plan","java","mods","runtime","boot"], step: "mods", done: 1, total: 4}` gives
    `items.map(x => x.state)` == `["done","done","now","later","later"]`;
  - `value` == `(2 + 0.25) / 5`;
  - `label` == `"Downloading the mods: 1 of 4"`.

- [ ] **Step 6: Run**

Run: `python -m pytest tests/test_setup_progress.py tests/test_ui_mods_and_packs.py tests/test_manager.py -q`
Expected: PASS

- [ ] **Step 7: Commit** `feat: steps and a progress bar while a server is made (49)`

### Task 4: Make a modpack (the file)

**Files:**
- Create: `src/craft_conductor/makepack.py`
- Modify: `src/craft_conductor/web.py` (routes and `_dispatch` for the download), `src/craft_conductor/access.py`
- Test: `tests/test_make_modpack.py` (new)

**Interfaces:**
- **`makepack.FORMATS = ("mrpack", "curseforge")`.**
- **`makepack.contents(m, fmt: str) -> dict`:**
  - Returns `{"name": str, "filename": str, "included": [{"name", "side"}], "left_out": [{"name", "why"}]}`.
  - Raises `ValueError` for an unknown format, or a server that doesn't run mods (`m.loader.name` not
    in fabric/quilt/forge/neoforge), or one not installed.
- **`makepack.build(m, fmt: str) -> tuple[str, bytes]`:** the file name and the zip's bytes.
- **The `why` texts (exact):**
  - "only on CurseForge: a Modrinth pack can't link to it"
  - "only on Modrinth: a CurseForge pack can't link to it"
  - "added by hand: not on a mod site"
  - "a datapack for the world, not a mod"
  - "Modrinth no longer has this file"
- **`filename`:** `re.sub(r"[^A-Za-z0-9._ -]+", "_", server_name).strip() or "modpack"`, then
  `-YYYY-MM-DD.mrpack` or `.zip`.
- **Routes** (both `mods.view` in `SERVER_ROUTES`):
  - `GET /api/modpack/make?format=` → `contents`;
  - `GET /api/modpack/make/download?format=` → the file, sent in `_dispatch` with
    `Content-Disposition: attachment; filename="<filename>"`, `application/zip` for CurseForge and
    `application/x-modrinth-modpack+zip` for mrpack.
  - A `ValueError` gives 400.

- [ ] **Step 1: Write the failing tests** in `tests/test_make_modpack.py`.
  - **The server** (`make_config`, `manager`, `update`), with:
    - Modrinth mod `BOTH` (client and server required);
    - `SRV` (`client_side="unsupported"`);
    - `OPT` (required False);
    - players-only `CLI` via `[client] mods` (`server_side="unsupported"`);
    - a CurseForge mod (use the existing CurseForge test fixture pattern from
      `tests/test_curseforge*.py`, or put a `ModFile(source="curseforge", ...)` straight into the
      lock);
    - a hand-added jar `mine.jar` in the mods folder;
    - a datapack ModFile.
  - **Modrinth's batch answer** `http.json[f"{MODRINTH}/versions"]`: a callable returning each
    version with `files[0]` `hashes` sha1+sha512 and `size`.
  - `test_an_mrpack_links_modrinth_files_only`:
    - Open `build(m, "mrpack")[1]` as a zip. Its names are exactly `["modrinth.index.json"]`.
    - `index["formatVersion"] == 1`, `index["game"] == "minecraft"`, and
      `index["dependencies"] == {"minecraft": "1.21.1", "fabric-loader": <lock's loader version>}`.
    - The `env` per mod:
      - BOTH `{client: required, server: required}`;
      - SRV `{client: unsupported, server: required}`;
      - OPT `server: optional`;
      - CLI `{client: required, server: unsupported}`.
    - Every `downloads[0]` starts with `https://cdn.modrinth.com/`; each file has `fileSize`, sha1 and
      sha512.
    - The CurseForge mod, `mine.jar` and the datapack are in `contents(m, "mrpack")["left_out"]`
      with the exact whys, and are named in `index["summary"]`.
  - `test_a_curseforge_pack_lists_project_and_file_ids`:
    - The zip names are `{"manifest.json", "modlist.html"}`.
    - `manifest["minecraft"]["modLoaders"] == [{"id": "fabric-<version>", "primary": True}]`.
    - `manifest["files"] == [{"projectID": <int>, "fileID": <int>, "required": True}]`.
    - `manifest["overrides"] == "overrides"`.
    - The Modrinth mods are in `left_out` with "only on Modrinth: …", and modlist.html has
      "Not included" and each left-out name, HTML-escaped (a mod named `<b>x</b>` appears escaped).
  - `test_the_file_name_is_safe`: server name `Bob's "Pack"/../x` gives a filename matching
    `^[A-Za-z0-9._ -]+-\d{4}-\d{2}-\d{2}\.mrpack$`.
  - `test_not_offered_for_plugin_or_vanilla_servers`: `contents` raises `ValueError` for a paper
    config.
  - `test_the_routes_and_permission(hub_env)`:
    - GET `/api/servers/alpha/modpack/make?format=mrpack` → 200.
    - `format=zip` → 400.
    - The download → 200, `Content-Disposition` attachment.
    - A person with no `mods.view` → 403 (use the `access` test helpers the server-icon tests used).

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tests/test_make_modpack.py -q`
Expected: FAIL (no module `makepack`).

- [ ] **Step 3: Implement `makepack.py`.**
  - **What goes in:**
    - `m.lock.mods`, with sides from `clientpack.players_mods(m, m.lock.mods, lk.minecraft,
      lk.loader_version, lk.java_major)` (the `project` → `side` of its `mods`);
    - a lock mod not in the players' list is server-only;
    - players' entries not on the server are players-only (local `local:` URLs are hand-added);
    - `m.unmanaged_jars()` are hand-added.
  - **Modrinth hashes and sizes:** one `GET {API}/versions` with `ids=json.dumps(sorted(ids))`. A
    version Modrinth doesn't return is left out with "Modrinth no longer has this file".
  - **Cached** for 300 s, keyed by `(m.config.root, fmt, the lock's (key, version_id) tuple, client
    mods)`, so the dialog's look and the download don't ask twice.
  - `modlist.html` uses `html.escape`.
  - The zip is built in memory with `ZIP_DEFLATED`.

- [ ] **Step 4: Routes and access**, as in Interfaces.

- [ ] **Step 5: Run**

Run: `python -m pytest tests/test_make_modpack.py -q`
Expected: PASS

- [ ] **Step 6: Commit** `feat: make a modpack from a server's mods (53)`

### Task 5: Make a modpack (the page)

**Files:**
- Modify: `src/craft_conductor/webui/app.js` (the Mods page: a **Make a modpack…** button opening a
  dialog)
- Modify: `src/craft_conductor/webui/style.css`
- Test: `tests/ui_mods_and_packs.cjs`

**Interfaces:**
- Consumes: Task 4's routes.
- The button is shown only with `can("mods.view")`, the loader in fabric/quilt/forge/neoforge, and
  the server installed.
- **The dialog:**
  - A radio group: **Modrinth (.mrpack)** / **CurseForge (.zip)**.
  - The summary `N mod(s) go in` from `included`.
  - **Not included** with each `name — why`.
  - **Download**: an `<a download>` to `scoped("/api/modpack/make/download?format=…")`.
  - Changing the format asks again.

- [ ] **Step 1: Add to `tests/ui_mods_and_packs.cjs`.**
  - As the owner (same login steps as `ui_recent_and_icon.cjs`), open `#s/alpha/mods`, then
    **Make a modpack…**.
  - The dialog shows "Modrinth (.mrpack)".
  - Choose CurseForge: the Download link's href contains `format=curseforge`.
  - `page.waitForEvent("download")` after clicking Download gives a file name ending `.zip`.
  - No page errors.

- [ ] **Step 2: Run to see it fail**

Run: `python -m pytest tests/test_ui_mods_and_packs.py -q`
Expected: FAIL (no button).

- [ ] **Step 3: Implement the button and dialog** with the page's existing modal pattern (the one
  `startExport` uses).

- [ ] **Step 4: Run**

Run: `python -m pytest tests/test_ui_mods_and_packs.py -q`
Expected: PASS

- [ ] **Step 5: Commit** `feat: Make a modpack on the Mods page (53)`

### Task 6: Help, translations, changelog, demo, real-world tests, screenshots

**Files:**
- Modify:
  - `src/craft_conductor/webui/manual.md` (`## Creating a server`: the progress and the pack check;
    `## Mods`: **Make a modpack…**);
  - `HELP` in app.js (the mods topic, if it lists the page's buttons);
  - `webui/i18n/*.json`;
  - `CHANGELOG.md` (new `## 0.31.0 (not released yet)` section: Added 49, 53; Changed 54);
  - `TODO.md` (tick 48 "Shipped in 0.29.0", 49 "No game: just the progress bar", 53, 54);
  - `testing/catalog.json`;
  - `site/demo/app/sim/routes-server.js` (simulated `/api/modpack/make` routes);
  - `src/craft_conductor/webui/screenshots/*` (the Mods page and the creating-progress pictures, if
    they're taken).
- Test: `tests/test_website_demo_contract.py`, `test_the_manual_covers_every_page`, the i18n tests,
  `tests/test_screenshots.py`.

- [ ] **Step 1:** Write the manual, Help and changelog text in plain words, with the button names
  as in the app.
- [ ] **Step 2:** Translations for every new `t()` string, in all 9 languages, with a script in the
  scratchpad (indent=2).
- [ ] **Step 3:** The demo's simulated routes. Run
  `python -m pytest tests/test_website_demo_contract.py -q`. Expected: PASS.
- [ ] **Step 4:** Real-world tests (Extra type), one per item: 49, 53 (each format) and 54. Use
  `python tools/real_world_tests.py add-test`, then `validate`.
- [ ] **Step 5:** Screenshots. Run `tests/test_screenshots.py` with the env it documents; keep the
  shrinking. The update-available stop is a known older failure: retake what comes before it.
- [ ] **Step 6:** The full suite. Run `python -m pytest -q`. Expected: all pass (skips allowed).
- [ ] **Step 7: Commit** `docs: manual, help, translations, changelog and tests for the mods and modpacks items`
