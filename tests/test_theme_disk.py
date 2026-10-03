"""The dashboard's volume metric is live, bounded and tolerant of unavailable disks."""
from types import SimpleNamespace
from unittest.mock import patch

from craft_conductor.web import Api, STATIC, static_file
from test_web import running, login


def test_volume_usage_uses_existing_parent_before_server_install(tmp_path):
    api = object.__new__(Api)
    api.d = SimpleNamespace(m=SimpleNamespace(server_dir=tmp_path / "not-installed", config=SimpleNamespace(root=tmp_path)))
    with patch("craft_conductor.web.shutil.disk_usage", return_value=SimpleNamespace(total=100, used=40, free=60)) as read:
        assert api._disk_usage() == {"total_bytes": 100, "used_bytes": 40, "free_bytes": 60}
        read.assert_called_once_with(tmp_path)
    api.m.server_dir.mkdir()
    with patch("craft_conductor.web.shutil.disk_usage", side_effect=OSError("unmounted")):
        assert api._disk_usage() is None


def test_theme_is_packaged_and_served_with_css_content_type():
    from craft_conductor.joinui import STATIC as JOIN_STATIC
    name, content_type = STATIC["/craft-conductor-theme.css"]
    assert JOIN_STATIC["craft-conductor-theme.css"] == (name, content_type)
    assert content_type.startswith("text/css")
    body, etag = static_file(name)
    assert b"--accent:#FF3E00" in body and b"--accent:#D63300" in body
    assert etag


def test_single_server_navigation_summary_and_theme_are_available(running):
    daemon, client, config = running
    login(client)
    status, hub, _ = client.get("/api/hub")
    assert status == 200 and hub["single"] and hub["servers"][0]["join_requests"] == 0
    status, body, headers = client.get("/craft-conductor-theme.css")
    assert status == 200 and headers["Content-Type"].startswith("text/css")
    assert "--accent:#FF3E00" in body
    assert client.get("/api/status")[1]["disk"]["total_bytes"] > 0
