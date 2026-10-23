"""The archive search's fetch (archives.py): where a group's spectra go,
that nothing there is moved or overwritten, and that the wrap reads what a
folder came from. koloa's getters are stood in for: no archive is asked."""
import json
import os
import time

from pca2dgui import archives, wrapgen


def _group(names, lbl="NIRPS_HE", source="ESO"):
    def get(one, science, calib):
        with open(os.path.join(science, one["name"]), "w") as handle:
            handle.write("spectrum")
        return ""
    return dict(key="", obj="GJ1", lbl=lbl, source=source,
                input="*TCORR_A.fits", params=dict(BLAZE_CORRECTED=False),
                spectra=[dict(id=n, name=n) for n in names], get=get)


def test_a_folder_never_mixes_two_readers(tmp_path):
    group = _group(["a_TCORR_A.fits", "b_TCORR_A.fits"])
    assert archives.folder_for(str(tmp_path), group) == "GJ1"
    mine = tmp_path / "science" / "GJ1"
    mine.mkdir(parents=True)
    (mine / "a_TCORR_A.fits").write_text("x")
    # the same spectra, some there already: the same folder
    assert archives.folder_for(str(tmp_path), group) == "GJ1"
    # another reader's spectra there: a folder of its own
    (mine / "2950000t.fits").write_text("x")
    assert archives.folder_for(str(tmp_path), group) == "GJ1_NIRPS_HE_ESO"


def test_a_fetch_adds_and_says_where_from(tmp_path):
    keep = tmp_path / "science" / "GJ1"
    keep.mkdir(parents=True)
    (keep / "a_TCORR_A.fits").write_text("mine")
    box = archives.Archives()
    group = _group(["a_TCORR_A.fits", "b_TCORR_A.fits"])
    box.search = dict(state="done", target="GJ 1", teff=3478.0, groups=[
        dict(id="NIRPS:", inst="NIRPS", label="NIRPS", archive="ESO",
             lbl="NIRPS_HE", source="ESO", input=group["input"],
             params=group["params"], n=2, have=1, folder="GJ1", size_mb=24)])
    box._groups = {"NIRPS:": group}
    box.start_fetch(str(tmp_path), ["NIRPS:"])
    for _ in range(100):
        if box.status()["fetch"]["state"] != "running":
            break
        time.sleep(0.05)
    assert box.status()["fetch"]["state"] == "done"
    # what was there is as it was; the missing one is fetched
    assert (keep / "a_TCORR_A.fits").read_text() == "mine"
    assert (keep / "b_TCORR_A.fits").read_text() == "spectrum"
    origin = json.loads((keep / archives.ARCHIVE_FILE).read_text())
    assert origin["lbl"] == "NIRPS_HE" and origin["source"] == "ESO"
    assert origin["teff"] == 3478.0


def test_the_wrap_takes_the_reader_of_a_fetched_folder(tmp_path):
    folder = tmp_path / "science" / "GJ1"
    folder.mkdir(parents=True)
    (folder / archives.ARCHIVE_FILE).write_text(json.dumps(dict(
        lbl="NIRPS_HE", source="ESO", input="*TCORR_A.fits",
        params=dict(BLAZE_CORRECTED=False))))
    state = dict(data_dir=str(tmp_path), instrument="NIRPS_HE", source="ESO",
                 targets=["GJ1"], teff={"GJ1": 3478}, pca2d_on=False)
    built = wrapgen.build(state)
    assert built["errors"] == []
    assert built["rparams"]["INPUT_FILE"] == "*TCORR_A.fits"
    assert built["rparams"]["BLAZE_CORRECTED"] is False
    # read with another source: refused, saying which
    built = wrapgen.build(dict(state, source="CADC"))
    assert any("ESO" in e for e in built["errors"])


def test_two_readers_found_together_get_two_folders(tmp_path, monkeypatch):
    import types
    found = {"NIRPS": [_group(["n.fits"])],
             "ESPRESSO": [_group(["e.fits"], lbl="ESPRESSO", source="None")]}
    fake = types.SimpleNamespace(
        _ident=lambda target: dict(main="HD 225213"),
        groups=lambda target, inst, root, ident: found.get(inst, []),
        INSTRUMENTS={k: dict(label=k, archive=k, size=1.0) for k in
                     archives.INSTRUMENTS})
    import sys
    monkeypatch.setitem(sys.modules, "koloa", types.SimpleNamespace(lblrun=fake))
    monkeypatch.setitem(sys.modules, "koloa.lblrun", fake)
    monkeypatch.setattr(archives, "ROOT", str(tmp_path / "root"))
    box = archives.Archives()
    box.start_search("GJ 1", ["NIRPS", "ESPRESSO"], str(tmp_path))
    for _ in range(100):
        if box.status()["search"]["state"] != "running":
            break
        time.sleep(0.05)
    folders = {r["lbl"]: r["folder"] for r in box.status()["search"]["groups"]}
    # whichever answered first keeps the star's name, the other its reader's
    first, second = sorted(folders.values())
    assert first == "GJ1" and second in ("GJ1_ESPRESSO_None", "GJ1_NIRPS_HE_ESO")
