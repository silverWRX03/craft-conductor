"""The self-updater fails closed: only a newer version, only bytes that match the release's
published SHA-256, and the running copy is untouched whenever anything doesn't check out."""

from __future__ import annotations

import hashlib
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from craft_conductor import config as configmod, selfupdate, web
from craft_conductor.http import HttpClient, TooBig

SUMS_URL = "https://dl.test/SHA256SUMS.txt"


def publish(http, served: bytes, published: bytes | None = None, version: str = "99.0.0",
            sums: str | None = None, size: int | None = None) -> selfupdate.Release:
    """A release of this platform's executable: ``served`` is what the download gives, ``published``
    what SHA256SUMS.txt (and GitHub's size) describe."""
    name = selfupdate.asset_name()
    published = served if published is None else published
    http.files[f"https://dl.test/{name}"] = served
    http.files[SUMS_URL] = (sums if sums is not None else
                            f"{hashlib.sha256(published).hexdigest()}  {name}\n").encode()
    return selfupdate.Release(version, f"v{version}", "https://github.test/r", "",
                              {name: f"https://dl.test/{name}", "SHA256SUMS.txt": SUMS_URL},
                              {name: len(published) if size is None else size})


@pytest.fixture
def exe(tmp_path):
    folder = tmp_path / "app"
    folder.mkdir()
    path = folder / "craft-conductor"
    path.write_bytes(b"CURRENT")
    return path


def untouched(exe: Path) -> bool:
    """The running copy is as it was, and nothing half-downloaded was left next to it."""
    return exe.read_bytes() == b"CURRENT" and sorted(p.name for p in exe.parent.iterdir()) == [exe.name]


def test_downgrades_and_reinstalls_are_refused(http, exe):
    for version in ("0.1.0", selfupdate.__version__, f"{selfupdate.__version__}b1"):
        release = publish(http, b"OLDER", version=version)
        with pytest.raises(selfupdate.SelfUpdateError, match="isn't newer"):
            selfupdate.install_binary(release, exe, http)
        with pytest.raises(selfupdate.SelfUpdateError, match="isn't newer"):
            selfupdate.install(release, http=http)
        assert untouched(exe)
    assert http.downloads == []  # refused before anything was fetched


def test_a_beta_is_never_replaced_by_an_older_stable(http, exe):
    release = publish(http, b"NEW", version="2.0.0")
    with pytest.raises(selfupdate.SelfUpdateError, match="isn't newer"):
        selfupdate.install_binary(release, exe, http, current="2.0.1b1")
    assert selfupdate.install_binary(release, exe, http, current="2.0.0rc1") == "installed Craft Conductor 2.0.0"


def test_a_truncated_download_is_refused(http, exe):
    release = publish(http, b"NEW-BIN", published=b"NEW-BINARY")  # cut short on the way
    with pytest.raises(selfupdate.VerificationError, match="nothing was changed"):
        selfupdate.install_binary(release, exe, http)
    assert untouched(exe)


def test_a_tampered_download_is_refused(http, exe):
    release = publish(http, b"EVIL-BINARY", published=b"REAL-BINARY")
    with pytest.raises(selfupdate.VerificationError):
        selfupdate.install_binary(release, exe, http)
    assert untouched(exe)


def test_a_download_bigger_than_published_is_cut_off(http, exe):
    release = publish(http, b"NEW-BINARY" * 100, size=10)
    with pytest.raises(selfupdate.VerificationError):
        selfupdate.install_binary(release, exe, http)
    assert untouched(exe)
    release.sizes[selfupdate.asset_name()] = selfupdate.MAX_DOWNLOAD + 1
    with pytest.raises(selfupdate.VerificationError, match="impossible size"):
        selfupdate.install_binary(release, exe, http)


@pytest.mark.parametrize("sums, why", [
    ("", "no entry"),
    ("abc  {name}\n", "broken entry"),
    ("{good}  {name}\n{other}  {name}\n", "two different entries"),
    ("{good}  {name}.old\n{good}  other-{name}\n", "no entry"),
])
def test_checksum_files_that_cant_vouch_for_the_download_are_refused(http, exe, sums, why):
    name = selfupdate.asset_name()
    text = sums.format(name=name, good=hashlib.sha256(b"NEW").hexdigest(), other="0" * 64)
    release = publish(http, b"NEW", sums=text)
    with pytest.raises(selfupdate.VerificationError, match=why):
        selfupdate.install_binary(release, exe, http)
    assert untouched(exe)


def test_a_release_without_checksums_installs_nothing(http, exe):
    release = publish(http, b"NEW")
    del release.assets["SHA256SUMS.txt"]
    with pytest.raises(selfupdate.VerificationError, match="SHA256SUMS"):
        selfupdate.install_binary(release, exe, http)
    assert untouched(exe) and http.downloads == []


def test_the_good_download_replaces_the_running_copy(http, exe):
    release = publish(http, b"NEW-BINARY")
    assert selfupdate.install_binary(release, exe, http) == "installed Craft Conductor 99.0.0"
    assert exe.read_bytes() == b"NEW-BINARY"


def test_pip_installs_need_the_releases_own_verified_wheel(http, monkeypatch):
    monkeypatch.setattr(selfupdate, "frozen", lambda: False)
    ran = []
    runner = lambda argv, **kw: ran.append(argv) or subprocess.CompletedProcess(argv, 0, "", "")  # noqa: E731
    bare = selfupdate.Release("99.0.0", "v99.0.0", "https://github.test/r", "", {"SHA256SUMS.txt": SUMS_URL})
    with pytest.raises(selfupdate.SelfUpdateError, match="no Python package"):
        selfupdate.install_wheel(bare, runner, http)
    other = selfupdate.Release("99.0.0", "v99.0.0", "", "", {"craft_conductor-98.0.0-py3-none-any.whl": "https://dl.test/w"})
    with pytest.raises(selfupdate.SelfUpdateError, match="no Python package"):
        selfupdate.wheel_name(other)  # (a wheel of another version isn't this release's)
    assert ran == []


def test_stable_never_offers_a_beta(http):
    http.json[selfupdate.RELEASES] = [
        {"tag_name": "v5.0.0b1", "prerelease": False},   # mislabelled on GitHub: the version says beta
        {"tag_name": "v4.1.0", "prerelease": True},      # flagged as a pre-release on GitHub
        {"tag_name": "v4.0.0"},
        {"tag_name": "v6.0.0", "draft": True},
        {"tag_name": "nightly"},                          # can't be compared: never offered
    ]
    assert selfupdate.check(http, "1.0.0").version == "4.0.0"
    assert selfupdate.check(http, "1.0.0", channel="stable").version == "4.0.0"
    assert selfupdate.check(http, "1.0.0", channel="nonsense").version == "4.0.0"  # unknown: stable
    beta = selfupdate.check(http, "1.0.0", channel="beta")
    assert beta.version == "5.0.0b1" and beta.prerelease
    assert selfupdate.check(http, "5.0.0b1", channel="stable") is None  # left beta: wait for a newer stable


def test_the_update_channel_is_stable_unless_chosen(tmp_path):
    from craft_conductor.config import ConfigError
    assert configmod.Config.__dataclass_fields__["self_update_channel"].default == "stable"
    root = tmp_path / "s"
    root.mkdir()
    (root / configmod.CONFIG_NAME).write_text(configmod.render_template("fabric", "latest"))
    assert configmod.load(root).self_update_channel == "stable"
    configmod.set_value(root / configmod.CONFIG_NAME, "craft-conductor", "update_channel", '"beta"')
    assert configmod.load(root).self_update_channel == "beta"
    configmod.set_value(root / configmod.CONFIG_NAME, "craft-conductor", "update_channel", '"nightly"')
    with pytest.raises(ConfigError):
        configmod.load(root)


def test_choosing_the_channel_is_for_the_owner_only(hub_env):
    from test_hub import login
    hub, c = hub_env
    assert hub.update_channel() == "stable"
    login(c)
    assert c.get("/api/hub")[1]["update_channel"] == "stable"
    assert c.post("/api/self-update/channel", {"channel": "nightly"})[0] == 400
    status, body, _ = c.post("/api/self-update/channel", {"channel": "beta"})
    assert status == 200 and body["channel"] == "beta" and hub.update_channel() == "beta"
    assert c.post("/api/self-update/channel", {"channel": "stable"})[0] == 200 and hub.update_channel() == "stable"
    # A paired phone can't change it (nor install updates).
    assert not web.device_allowed("POST", "/api/self-update/channel")
    assert not web.device_allowed("POST", "/api/self-update/apply")


class _Endless(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()  # no Content-Length: only the byte count can stop it
        try:
            for _ in range(64):
                self.wfile.write(b"x" * 65536)
        except OSError:
            pass

    def log_message(self, *a):
        pass


def test_the_http_client_stops_a_download_past_its_limit(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Endless)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        dest = tmp_path / "dl" / "file"
        with pytest.raises(TooBig):
            HttpClient(retries=1).download(f"http://127.0.0.1:{server.server_address[1]}/f", dest, max_bytes=100_000)
        assert not dest.exists() and list(dest.parent.iterdir()) == []  # the partial file is gone too
    finally:
        server.shutdown()
        server.server_close()
