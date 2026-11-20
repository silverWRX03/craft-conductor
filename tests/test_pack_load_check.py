"""No load check for a modpack's own mods (roadmap 54): the pack's maker checked them. Mods added on
top are still checked, at setup (filecheck.py) and at install (Manager.mod_problems)."""

import hashlib

from craft_conductor import config as configmod, filecheck, modpack, packupdate
from craft_conductor.config import ModSpec, Pin
from craft_conductor.mods.modrinth import API as MODRINTH

from test_hub import login
from test_manager import manager, update
from test_mod_checks_web import finished
from test_modcheck import fabric
from test_pack_update import publish

PACKMOD = fabric("packmod", "1.0", {"missingthing": "*"}, "Pack Mod")   # (needs a mod nobody has)
FINE = fabric("finemod", "1.0", {}, "Fine Mod")
ADDED = fabric("added", "1.0", {"alsomissing": "*"}, "Added")


def build(http, modrinth, pid: str, vid: str, name: str, content: bytes) -> dict:
    """A mod's build on Modrinth with these contents, and its line in a pack's index."""
    if f"{MODRINTH}/project/{pid}" not in http.json:
        modrinth.project(pid, name.lower().replace(" ", ""), name)
    url = f"https://cdn.modrinth.com/data/{pid}/versions/{vid}/{name.replace(' ', '')}-{vid}.jar"
    http.files[url] = content
    sha1 = hashlib.sha1(content).hexdigest()
    http.json[f"{MODRINTH}/version/{vid}"] = {
        "id": vid, "project_id": pid, "version_number": vid, "version_type": "release", "game_versions": ["1.21.1"],
        "loaders": ["fabric"], "dependencies": [],
        "files": [{"url": url, "filename": url.rsplit("/", 1)[1], "primary": True, "hashes": {"sha1": sha1}}]}
    return {"path": f"mods/{url.rsplit('/', 1)[1]}", "downloads": [url], "hashes": {"sha1": sha1},
            "env": {"server": "required", "client": "required"}}


def a_pack(http, modrinth, *more) -> list[dict]:
    lines = [build(http, modrinth, "PACKMODA", "PACKV100", "Pack Mod", PACKMOD), *more]
    publish(http, "PACKV001", "Test Pack 1.0", "2026-01-01T00:00:00Z", lines, {})
    return lines


def added_mod(modrinth):
    modrinth.project("ADDED", "added", "Added")
    modrinth.version("ADDED", "1.0", ["1.21.1"], content=ADDED)


BODY = {"loader": "fabric", "minecraft": "1.21.1", "motd": "Pack", "accept_eula": True, "modpack_version": "PACKV001"}


# ------------------------------------------------------------------ the setup page
def test_pack_only_setup_check_answers_at_once(hub_env, http, modrinth):
    hub, c = hub_env
    login(c)
    lines = a_pack(http, modrinth)
    result = finished(c, c.post("/api/hub/mods/filecheck", BODY)[1])
    assert result == {"ok": True, "problems": [], "unreadable": [], "pack_only": True}
    assert lines[0]["downloads"][0] not in http.downloads   # (nothing downloaded to check)


def test_the_packs_own_problems_are_skipped_but_added_mods_are_checked(hub_env, http, modrinth):
    hub, c = hub_env
    login(c)
    a_pack(http, modrinth)
    added_mod(modrinth)
    result = finished(c, c.post("/api/hub/mods/filecheck", {**BODY, "mods": ["added"]})[1])
    assert [p["mod"] for p in result["problems"]] == ["Added"]
    code, r, _ = c.post("/api/hub/create", {**BODY, "mods": ["added"]})
    assert code == 409   # (Create my server still waits for the added mod)


def test_a_removed_pack_mod_keeps_missing_problems(hub_env, http, modrinth):
    hub, c = hub_env
    login(c)
    cut = build(http, modrinth, "CUTMODAA", "CUTV0001", "Cut Mod", FINE)
    a_pack(http, modrinth, cut)
    added_mod(modrinth)
    body = {**BODY, "mods": ["added"], "modpack_exclude": [cut["path"]]}
    result = finished(c, c.post("/api/hub/mods/filecheck", body)[1])
    assert sorted(p["mod"] for p in result["problems"]) == ["Added", "Pack Mod"]


def test_pack_own_rule():
    pack = {"modrinth:A", "local:own.jar"}

    def p(key, needs_key=None, kind="missing"):
        return {"key": key, "needs_key": needs_key, "kind": kind}
    assert filecheck.pack_own(p("modrinth:A"), pack, excluded=False)
    assert filecheck.pack_own(p("modrinth:A", "local:own.jar", "version"), pack, excluded=False)
    assert not filecheck.pack_own(p("modrinth:A", "modrinth:ADDED", "version"), pack, excluded=False)
    assert not filecheck.pack_own(p("modrinth:ADDED"), pack, excluded=False)
    assert not filecheck.pack_own(p("modrinth:A"), pack, excluded=True)        # (a mod left out may be what's missing)
    assert filecheck.pack_own(p("modrinth:A", kind="minecraft"), pack, excluded=True)
    assert not filecheck.pack_own(p(None), pack, excluded=False)
