"""Downloads on a new Windows computer, whose certificate store doesn't have every root yet (#64).

Windows ships with only some of the root certificates it trusts and fetches the others from
Windows Update the first time its own certificate check needs one. Python's ssl only reads the
store, so on a fresh Windows 11 the Java download from GitHub failed with "certificate verify
failed: unable to get local issuer certificate". Here a pretend HTTPS server stands in for GitHub
and a pretend Windows for the certificate store.
"""

import hashlib
import http.server
import ssl
import sys
import threading

import pytest

from craft_conductor import http as httpmod
from craft_conductor import tlscert

BODY = b"pretend Java archive"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """An HTTPS server for "localhost", with a certificate this computer doesn't trust yet."""
    folder = tmp_path_factory.mktemp("site")
    key = tlscert.generate_key()
    der = tlscert.make_certificate(key, name="localhost")
    cert, key_file = folder / "cert.pem", folder / "key.pem"
    cert.write_text(ssl.DER_cert_to_PEM_cert(der))
    key_file.write_text(tlscert.key_pem(key))

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(BODY)))
            self.end_headers()
            self.wfile.write(BODY)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = tlscert.server_context(cert, key_file).wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield {"url": f"https://localhost:{server.server_address[1]}/OpenJDK25U-jre.zip", "cert": cert, "der": der}
    server.shutdown()


@pytest.fixture
def windows(monkeypatch, site):
    """A pretend fresh Windows: the site's root isn't in the store until Windows is asked to check
    the site's certificate itself (then it fetches the root, as Windows Update would)."""
    store = {"has_root": False, "asked": []}

    def default_context():
        if store["has_root"]:
            return ssl.create_default_context(cafile=str(site["cert"]))
        return ssl.create_default_context()  # this computer's roots: not the pretend site's

    def check_chain(der):
        store["asked"].append(der)
        store["has_root"] = store["can_fetch"]
        return True

    store["can_fetch"] = True
    monkeypatch.setattr(ssl, "_create_default_https_context", default_context)
    monkeypatch.setattr(httpmod, "_WINDOWS", True, raising=False)
    monkeypatch.setattr(httpmod, "_windows_check_chain", check_chain, raising=False)
    monkeypatch.setattr(httpmod, "_asked_windows", set(), raising=False)
    monkeypatch.setattr(httpmod.time, "sleep", lambda s: None)
    return store


def test_download_on_a_fresh_windows_gets_the_missing_root(tmp_path, site, windows):
    dest = tmp_path / "java.zip"
    httpmod.HttpClient().download(site["url"], dest, sha256=hashlib.sha256(BODY).hexdigest())
    assert dest.read_bytes() == BODY
    assert windows["asked"] == [site["der"]]  # Windows checked the site's own certificate, once
    # Later downloads just work: nothing more to ask.
    httpmod.HttpClient().download(site["url"], tmp_path / "again.zip")
    assert len(windows["asked"]) == 1


def test_a_certificate_windows_cant_vouch_for_still_fails(tmp_path, site, windows):
    windows["can_fetch"] = False  # (not a root Microsoft trusts, or Windows Update unreachable)
    with pytest.raises(httpmod.HttpError, match="CERTIFICATE_VERIFY_FAILED"):
        httpmod.HttpClient().download(site["url"], tmp_path / "java.zip")
    assert len(windows["asked"]) == 1  # asked once for that site, not on every retry
    assert not (tmp_path / "java.zip").exists()


def test_other_computers_are_left_alone(tmp_path, site, windows, monkeypatch):
    monkeypatch.setattr(httpmod, "_WINDOWS", False)
    with pytest.raises(httpmod.HttpError, match="CERTIFICATE_VERIFY_FAILED"):
        httpmod.HttpClient().download(site["url"], tmp_path / "java.zip")
    assert windows["asked"] == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' own certificate check")
def test_windows_checks_a_certificate_chain(site):
    # The real call: Windows builds the chain (this certificate isn't trusted, which is fine).
    assert httpmod._windows_check_chain(site["der"]) is True
    assert httpmod._windows_check_chain(b"not a certificate") is False



def test_not_through_a_proxy(tmp_path, site, windows, monkeypatch):
    # Behind a proxy, fetching the certificate would go around it, so Windows isn't asked.
    import urllib.error
    import urllib.request

    def refused(self, req):
        assert req.host == "proxy.example:3128"
        raise urllib.error.URLError(ssl.SSLCertVerificationError("unable to get local issuer certificate"))
    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", refused)
    req = urllib.request.Request(site["url"])
    req.set_proxy("proxy.example:3128", "https")
    with pytest.raises(urllib.error.URLError):
        httpmod._HTTPSHandler().https_open(req)
    assert windows["asked"] == []
