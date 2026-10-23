"""The background mosaic: one per state of the folder and per theme."""
import os

import numpy as np

from pca2dgui import backdrop


def _folder(tmp_path):
    rdb = tmp_path / "data" / "lblrdb"
    rdb.mkdir(parents=True)
    rng = np.random.default_rng(1)
    rows = ["rjd\tvrad\tsvrad\tBERV", "---\t----\t-----\t----"]
    for i in range(20):
        rows.append("%.3f\t%.2f\t2.0\t%.3f" % (60000 + 3.1 * i,
                                                rng.normal(0, 5),
                                                20 * np.sin(i / 3)))
    (rdb / "lbl_STAR_STAR.rdb").write_text("\n".join(rows) + "\n")
    return str(tmp_path / "data")


def test_each_theme_has_its_own_mosaic(tmp_path, monkeypatch):
    monkeypatch.setattr(backdrop, "HOME", str(tmp_path / "backdrops"))
    data_dir = _folder(tmp_path)
    light, ready = backdrop.path_of(data_dir, "light")
    dark, _ = backdrop.path_of(data_dir, "dark")
    assert light != dark and not ready
    # anything else is the light one, the window's default
    assert backdrop.path_of(data_dir, "nonsense")[0] == light
    for theme, path in (("light", light), ("dark", dark)):
        backdrop.draw(backdrop.sources(data_dir), path, theme)
        assert backdrop.path_of(data_dir, theme) == (path, True)


def test_nothing_to_draw(tmp_path):
    (tmp_path / "empty").mkdir()
    assert backdrop.path_of(str(tmp_path / "empty"), "dark") == (None, False)


def test_only_the_last_mosaics_are_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(backdrop, "HOME", str(tmp_path / "backdrops"))
    monkeypatch.setattr(backdrop, "KEEP", 1)
    data_dir = _folder(tmp_path)
    light, _ = backdrop.path_of(data_dir, "light")
    dark, _ = backdrop.path_of(data_dir, "dark")
    backdrop.draw(backdrop.sources(data_dir), light, "light")
    os.utime(light, (1, 1))
    backdrop.draw(backdrop.sources(data_dir), dark, "dark")
    assert os.listdir(backdrop.HOME) == [os.path.basename(dark)]
