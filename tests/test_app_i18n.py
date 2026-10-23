"""The two languages, and the server end to end on a free port."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from pca2dgui import app, i18n


def test_both_languages_have_every_word():
    assert set(i18n.EN) == set(i18n.FR)
    for key in i18n.EN:
        assert i18n.EN[key].count("%s") == i18n.FR[key].count("%s"), key
    for key, (labels, helps) in i18n.OPTIONS.items():
        assert len(labels) == 2 and all(labels), key
        assert helps is None or (len(helps) == 2 and all(helps)), key


def test_french_says_vous_never_tu():
    words = " ".join(i18n.FR.values()).lower().replace("'", " ").split()
    assert not {"tu", "toi", "ton", "ta", "tes"} & set(words)


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "STATE_FILE", str(tmp_path / "state.json"))
    (tmp_path / "data" / "science" / "STAR").mkdir(parents=True)
    (tmp_path / "data" / "reports").mkdir()
    (tmp_path / "data" / "reports" / "r.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "secret.pdf").write_bytes(b"%PDF-1.4")
    app.Handler.ctx = app.Context(str(tmp_path / "data"))
    srv = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % srv.server_address[1], tmp_path
    srv.shutdown()


def _get(url):
    with urllib.request.urlopen(url) as response:
        return response.status, response.read()


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def test_pages_and_json(server):
    base, tmp = server
    status, page = _get(base + "/")
    assert status == 200 and b"<title>LBL</title>" in page
    strings = json.loads(_get(base + "/api/strings?lang=fr")[1])
    assert strings["tab_targets"] == "Cibles"
    state = json.loads(_get(base + "/api/state")[1])
    assert state["state"]["data_dir"].endswith("data")
    built = _post(base + "/api/build", dict(
        data_dir=str(tmp / "data"), instrument="NIRPS_HE", source="CADC",
        targets=["STAR"], teff={"STAR": 3300}))
    assert built["errors"] == [] and "lbl_wrap.main" in built["wrap"]


def test_files_are_served_from_the_data_folder_only(server):
    base, tmp = server
    status, body = _get(base + "/file?path=%s" % (tmp / "data" / "reports"
                                                    / "r.pdf"))
    assert status == 200 and body.startswith(b"%PDF")
    with pytest.raises(urllib.error.HTTPError) as error:
        _get(base + "/file?path=%s" % (tmp / "secret.pdf"))
    assert error.value.code == 403
