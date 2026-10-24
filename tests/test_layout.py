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
