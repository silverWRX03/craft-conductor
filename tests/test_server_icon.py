"""The picture players see in Minecraft's server list (server-icon.png), chosen in a server's Settings."""

from __future__ import annotations

import base64
import struct
import zlib

import pytest

from craft_conductor import servericon

from test_access import owner_ready
from test_remote import invite


def png(width=64, height=64, bad_crc=False) -> bytes:
    """A real PNG (one grey colour), made without an image library."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) ^ (1 if bad_crc and kind == b"IHDR" else 0)
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# ------------------------------------------------------------------ the checks
def test_a_64_by_64_png_is_saved(tmp_path):
    servericon.save(tmp_path, png())
    assert (tmp_path / servericon.FILE).read_bytes() == png()
    assert servericon.stamp(tmp_path) is not None


@pytest.mark.parametrize("data, words", [
    (png(32, 32), "64 × 64"),
    (b"GIF89a" + b"\x00" * 40, "PNG"),
    (png(bad_crc=True), "damaged"),
    (png()[:20], "PNG"),
    (png() + b"\x00" * servericon.MAX_BYTES, "too big"),
], ids=["32x32", "gif", "bad-crc", "cut-short", "too-big"])
def test_anything_else_is_refused_and_the_icon_kept(tmp_path, data, words):
    servericon.save(tmp_path, png())
    with pytest.raises(ValueError, match=words):
        servericon.save(tmp_path, data)
    assert (tmp_path / servericon.FILE).read_bytes() == png()
    assert not list(tmp_path.glob("*.tmp"))


def test_remove_goes_back_to_minecrafts_default(tmp_path):
    assert servericon.remove(tmp_path) is False
    servericon.save(tmp_path, png())
    assert servericon.remove(tmp_path) is True
    assert not (tmp_path / servericon.FILE).exists() and servericon.stamp(tmp_path) is None


# ------------------------------------------------------------------ through the web server
def test_the_owner_sets_and_removes_the_icon(hub_env):
    hub, c = hub_env
    owner_ready(hub, c)
    assert c.get("/api/servers/alpha/server-icon")[0] == 404
    before = next(s for s in c.get("/api/hub")[1]["servers"] if s["id"] == "alpha")["icon"]
    assert before is None
    status, body, _ = c.post("/api/servers/alpha/server-icon", {"png": b64(png())})
    assert status == 200, body
    status, got, headers = c.get("/api/servers/alpha/server-icon")
    assert status == 200 and got == png() and headers["Content-Type"] == "image/png"
    assert next(s for s in c.get("/api/hub")[1]["servers"] if s["id"] == "alpha")["icon"]
    assert (hub.get("alpha").m.server_dir / "server-icon.png").read_bytes() == png()

    status, body, _ = c.post("/api/servers/alpha/server-icon", {"png": b64(png(16, 16))})
    assert status == 400 and "64 × 64" in body["error"]
    assert c.post("/api/servers/alpha/server-icon", {"png": "not base64!"})[0] == 400
    assert c.post("/api/servers/alpha/server-icon", {})[0] == 400

    assert c.post("/api/servers/alpha/server-icon/remove")[0] == 200
    assert c.get("/api/servers/alpha/server-icon")[0] == 404


def test_only_people_who_may_change_settings_set_the_icon(hub_env):
    hub, c = hub_env
    owner_ready(hub, c)
    assert c.post("/api/servers/alpha/server-icon", {"png": b64(png())})[0] == 200
    viewer, _ = invite(hub, c, "Vivian", {"alpha": ["status.view"]})
    assert viewer.get("/api/servers/alpha/server-icon")[0] == 200  # (seen on the server's card)
    assert viewer.post("/api/servers/alpha/server-icon", {"png": b64(png())})[0] == 403
    assert viewer.post("/api/servers/alpha/server-icon/remove")[0] == 403
    assert viewer.get("/api/servers/main/server-icon")[0] == 404  # (a server they weren't given)
    manager, _ = invite(hub, c, "Manny", {"alpha": ["status.view", "settings.safe"]})
    assert manager.post("/api/servers/alpha/server-icon/remove")[0] == 200


def test_only_a_real_icon_is_ever_served(tmp_path):
    """Whatever else is called server-icon.png (put there by hand, a mod or a link) is never sent to the page."""
    assert servericon.read(tmp_path) is None
    (tmp_path / servericon.FILE).write_bytes(b"not a picture, maybe a password")
    assert servericon.read(tmp_path) is None
    (tmp_path / servericon.FILE).write_bytes(png(128, 128))
    assert servericon.read(tmp_path) is None
    servericon.save(tmp_path, png())
    assert servericon.read(tmp_path) == png()


def test_a_link_called_server_icon_is_not_followed(tmp_path):
    secret = tmp_path / "elsewhere.png"
    secret.write_bytes(png())
    server = tmp_path / "server"
    server.mkdir()
    try:
        (server / servericon.FILE).symlink_to(secret)
    except OSError:
        pytest.skip("this computer doesn't allow making links")
    assert servericon.read(server) is None


def test_saving_never_writes_through_a_link(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me")
    server = tmp_path / "server"
    server.mkdir()
    try:
        (server / (servericon.FILE + ".tmp")).symlink_to(outside)
    except OSError:
        pytest.skip("this computer doesn't allow making links")
    servericon.save(server, png())
    assert outside.read_text() == "keep me"
    assert servericon.read(server) == png()


def test_a_leftover_temporary_file_is_replaced(tmp_path):
    (tmp_path / (servericon.FILE + ".tmp")).write_bytes(b"half a picture from a power cut")
    servericon.save(tmp_path, png())
    assert servericon.read(tmp_path) == png() and not (tmp_path / (servericon.FILE + ".tmp")).exists()
