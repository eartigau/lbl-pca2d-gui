"""The data source a folder's files say by their layout (targets.py), and
the wrap that refuses another: the CADC's t.fits run as APERO stopped LBL on
the first one (2026-10-24)."""
import numpy as np
from astropy.io import fits

from pca2dgui import targets, wrapgen


def _cadc(path):
    primary = fits.PrimaryHDU()
    primary.header["INSTRUME"] = "SPIRou"
    flux = fits.ImageHDU(np.zeros((2, 4)), name="FluxAB")
    flux.header["WAVEORDN"] = 49
    fits.HDUList([primary, flux, fits.ImageHDU(np.zeros((2, 4)),
                                               name="WaveAB")]).writeto(path)


def _apero(path):
    primary = fits.PrimaryHDU(np.zeros((2, 4)))
    primary.header["INSTRUME"] = "SPIRou"
    primary.header["WAVEORDN"] = 49
    primary.writeto(path)


def test_the_layout_says_the_source(tmp_path):
    for name, make, said in (("A", _cadc, "CADC"), ("B", _apero, "APERO")):
        folder = tmp_path / "science" / name
        folder.mkdir(parents=True)
        make(str(folder / "1t.fits"))
        assert targets.layout_of(str(tmp_path), name) == ("SPIROU", said)
        assert targets.read_file(str(folder / "1t.fits"))["source"] == said
    e2ds = tmp_path / "e2ds.fits"
    hdu = fits.PrimaryHDU(np.zeros((2, 4)))
    hdu.header["INSTRUME"] = "HARPS"
    hdu.writeto(str(e2ds))
    with fits.open(str(e2ds)) as hdulist:
        assert targets.layout_source("HARPS", hdulist) == "ORIG"


def test_the_wrap_refuses_a_source_the_files_are_not_for(tmp_path):
    folder = tmp_path / "science" / "TOI5695"
    folder.mkdir(parents=True)
    _cadc(str(folder / "3018320t.fits"))
    state = dict(data_dir=str(tmp_path), instrument="SPIROU", source="APERO",
                 targets=["TOI5695"], teff={"TOI5695": 3200}, pca2d_on=False)
    built = wrapgen.build(state)
    assert any("CADC" in e for e in built["errors"])
    assert wrapgen.build(dict(state, source="CADC"))["errors"] == []


def test_the_commented_wrap_reads_back(tmp_path):
    from pca2dgui import wrapload
    rparams = dict(INSTRUMENT="SPIROU", DATA_SOURCE="CADC", DATA_DIR="/x",
                   DATA_TYPES=["SCIENCE"], OBJECT_SCIENCE=["A"],
                   OBJECT_COMPARISON=["VETTED_GJ411"], OBJECT_TEFF=[3595],
                   RUN_LBL_TEMPLATE=True, MYKEY=3,
                   PCA2D=dict(n_star=1, n_earth=7, star_bias_nsig=10.0))
    text = wrapgen.render(rparams, "demo")
    # every setting has its comment, and the comments do not get in the way
    assert "# the folders of science/ to measure" in text
    assert "# the bias test (bias_nsig) in the star's frame" in text
    path = tmp_path / "wrap.py"
    path.write_text(text)
    back = wrapload.read(str(path))
    found = back.get("rparams", back)
    assert found["OBJECT_COMPARISON"] == ["VETTED_GJ411"]
    assert found["PCA2D"]["star_bias_nsig"] == 10.0
    assert found["MYKEY"] == 3


def test_an_old_window_wrap_is_written_commented():
    # the page can post a wrap made before the comments were: same values,
    #   so the window's own, commented, is written; one edited by hand stays
    rparams = dict(INSTRUMENT="SPIROU", DATA_SOURCE="CADC", DATA_DIR="/x",
                   DATA_TYPES=["SCIENCE"], OBJECT_SCIENCE=["A"],
                   OBJECT_COMPARISON=["A"], OBJECT_TEFF=[3500],
                   PCA2D=dict(n_star=1, n_earth=7))
    bare = "\n".join(line for line in wrapgen.render(rparams, "x").splitlines()
                     if not line.strip().startswith("#"))
    out = wrapgen.window_text(bare, rparams, "x")
    assert "# the folders of science/ to measure" in out
    edited = bare.replace("n_earth=7", "n_earth=5")
    assert wrapgen.window_text(edited, rparams, "x") == edited
