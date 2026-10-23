"""Reading targets from their headers, building a wrap from the window's
state, and what the cleanup may and may not delete."""
import os

import numpy as np
import pytest
from astropy.io import fits

from pca2dgui import cleanup, targets, wrapgen


def _apero(path, berv, mjd, snr=50.0):
    """An APERO-like t.fits: INSTRUME in the primary, EXTSNxxx, BERV and
    MJDMID on the science extension."""
    primary = fits.PrimaryHDU()
    primary.header["INSTRUME"] = "NIRPS"
    primary.header["OBJTEMP"] = 3300.0
    sci = fits.ImageHDU(np.zeros((2, 4)), name="FluxA")
    for order in range(5):
        sci.header["EXTSN%03d" % order] = snr + order
    sci.header["BERV"] = berv
    sci.header["MJDMID"] = mjd
    sci.header["EXPTIME"] = 600.0
    sci.header["DRSOBJN"] = "STAR"
    fits.HDUList([primary, sci]).writeto(path)


@pytest.fixture
def data_dir(tmp_path):
    star = tmp_path / "science" / "STAR"
    star.mkdir(parents=True)
    for i in range(4):
        _apero(star / ("%dt.fits" % i), berv=-10.0 + 5 * i, mjd=60000.4 + i)
    (tmp_path / "science" / "STAR_pca2d").mkdir()
    (tmp_path / "science" / "STAR_tc").mkdir()
    return tmp_path


def test_headers_and_the_derived_folders(data_dir):
    assert targets.target_names(str(data_dir)) == ["STAR"]
    record = targets.read_file(str(data_dir / "science" / "STAR" / "0t.fits"))
    assert record["instrument"] == "NIRPS"
    assert record["berv"] == -10.0 and record["mjd"] == 60000.4
    assert record["snr"] == 52.0 and record["teff"] == 3300.0
    assert record["object"] == "STAR"


def test_the_scanner_reads_once(data_dir, monkeypatch, tmp_path):
    monkeypatch.setattr(targets, "INDEX_HOME", str(tmp_path / "index"))
    scanner = targets.Scanner()
    scanner.start(str(data_dir))
    scanner.thread.join(30)
    rows = scanner.snapshot()["targets"]["STAR"]
    summary = targets.summary(rows)
    assert summary["files"] == 4 and summary["nights"] == 4
    assert summary["berv_span"] == 15.0
    calls = []
    monkeypatch.setattr(targets, "read_file",
                        lambda path: calls.append(path) or {})
    scanner.start(str(data_dir))
    scanner.thread.join(30)
    assert calls == []                       # nothing changed: nothing read


def _state(data_dir, **extra):
    state = dict(data_dir=str(data_dir), instrument="NIRPS_HE",
                 source="CADC", targets=["STAR"], teff={"STAR": 3300},
                 pca2d_on=True, pca2d={"n_earth": 5})
    state.update(extra)
    return state


def test_a_wrap_says_what_was_chosen_and_runs(data_dir):
    built = wrapgen.build(_state(data_dir))
    assert built["errors"] == []
    rparams = built["rparams"]
    assert rparams["OBJECT_SCIENCE"] == ["STAR"]
    assert rparams["OBJECT_COMPARISON"] == ["STAR"]
    assert rparams["PCA2D"] == dict(n_star=1, n_earth=5)
    text = wrapgen.render(rparams, "test")
    compile(text, "wrap.py", "exec")
    assert "lbl_wrap.main(rparams)" in text


def test_what_a_wrap_refuses(data_dir):
    assert wrapgen.build(_state(data_dir, targets=[]))["errors"]
    built = wrapgen.build(_state(data_dir, comparison={"STAR": "NOBODY"}))
    assert any("NOBODY" in e for e in built["errors"])
    built = wrapgen.build(_state(data_dir, pca2d={"input_name": "missing"}))
    assert any("missing" in e for e in built["errors"])
    built = wrapgen.build(_state(data_dir, pca2d={"n_star": 0}))
    assert any("n_star" in e for e in built["errors"])
    built = wrapgen.build(_state(data_dir, teff={}))
    assert built["errors"] == [] and built["warnings"]


def test_a_basis_of_another_instrument_is_refused(data_dir):
    folder = data_dir / "pca2d" / "components"
    folder.mkdir(parents=True)
    head = fits.Header()
    head["BASISNAM"] = "spirou_set"
    head["INSTRUME"] = "SPIROU"
    head["DATASRC"] = "CADC"
    fits.PrimaryHDU(header=head).writeto(
        folder / "PCA2D_Observer_spirou_set_spirou.fits")
    built = wrapgen.build(_state(data_dir, pca2d={"input_name": "spirou_set"}))
    assert any("refuses" in e for e in built["errors"])


def test_the_cleanup_deletes_only_what_can_be_remade(data_dir, tmp_path):
    cache = data_dir / "pca2d" / "cache" / "cube_x"
    cache.mkdir(parents=True)
    (cache / "data.npy").write_bytes(b"0" * 1000)
    rdb = data_dir / "lblrdb"
    rdb.mkdir()
    (rdb / "lbl_STAR.rdb").write_text("x")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "kept.fits").write_text("x")
    os.symlink(elsewhere, data_dir / "science" / "OTHER_pca2d")
    kinds = {os.path.relpath(item["path"], data_dir): item["kind"]
             for item in cleanup.survey(str(data_dir))}
    assert kinds["pca2d/cache"] == "scratch"
    assert kinds["lblrdb"] == "results"
    assert kinds["science/STAR"] == "data"
    assert kinds["science/OTHER_pca2d"] == "rebuildable"
    out = cleanup.delete(str(data_dir), [
        str(data_dir / "pca2d" / "cache"), str(rdb),
        str(data_dir / "science" / "STAR"),
        str(data_dir / "science" / "OTHER_pca2d")])
    done = {os.path.relpath(r["path"], data_dir): r["done"] for r in out}
    assert done == {"pca2d/cache": True, "lblrdb": False,
                    "science/STAR": False, "science/OTHER_pca2d": True}
    assert (elsewhere / "kept.fits").exists()     # the link went, not this
    assert (data_dir / "science" / "STAR").exists()


def test_nothing_is_deleted_while_a_run_works_in_the_folder(data_dir):
    import subprocess
    import sys
    import time
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                            cwd=str(data_dir))
    try:
        time.sleep(0.5)
        assert any(p["pid"] == proc.pid for p in cleanup.busy(str(data_dir)))
        cache = data_dir / "pca2d" / "cache"
        cache.mkdir(parents=True)
        out = cleanup.delete(str(data_dir), [str(cache)])
        assert out[0]["done"] is False and "run is going" in out[0]["why"]
        assert cache.exists()
    finally:
        proc.kill()
