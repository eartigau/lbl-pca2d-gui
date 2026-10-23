"""The window's background: a mosaic of the data folder's own LBL results,
drawn small and shown blurred behind the cards.

The tiles are what LBL leaves in a data folder: velocity curves (lblrdb), the
velocities against the BERV, their periodograms, the line-width and
temperature indicators, a stretch of a template (templates), and the
per-line velocities of one exposure (lblrv). Drawn without labels, in the
series colours of the window's theme (light or dark) on its background, then
kept as a PNG keyed by the files it was drawn from and the theme, so that it
is drawn once per state of the folder.
"""
from __future__ import annotations

import glob
import hashlib
import os
import threading

import numpy as np

#: where the drawn backgrounds are kept
HOME = os.path.expanduser("~/.lbl_pca2d_gui/backdrops")
#: the mosaic: columns, rows, and its size in pixels. Its marks are drawn
#:    heavy: the page scales it to the window and blurs it, and a curve of one
#:    pixel came out as a uniform haze
COLUMNS, ROWS = 4, 3
WIDTH, HEIGHT = 2200, 1240
#: how many drawn mosaics are kept (each is a few hundred kB; a folder that
#:    changes leaves the older ones behind)
KEEP = 8
#: the window's colours for each theme (app.css): page, tiles, spines, ticks,
#:    grid, and the series (validated categorical palettes for each surface)
THEMES = dict(
    dark=dict(page="#08111f", tile="#0d1628", spine="#2a3d5c",
              tick="#3c4d6b", grid="#1b2c47",
              series=("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181",
                      "#008300", "#9085e9", "#e66767")),
    light=dict(page="#e9eef6", tile="#ffffff", spine="#c9d4e4",
               tick="#b9c5d6", grid="#e6ecf4",
               series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4",
                       "#008300", "#6250d6", "#e34948")),
)

_lock = threading.Lock()
_running = set()


def _rdb(path):
    """An rdb's columns as float arrays (the header line, a dashes line,
    then the rows)."""
    with open(path) as handle:
        lines = [line.rstrip("\n") for line in handle if line.strip()]
    if len(lines) < 4:
        return None
    names = lines[0].split("\t")
    rows = [line.split("\t") for line in lines[2:]]
    out = {}
    for i, name in enumerate(names):
        try:
            out[name] = np.array([float(r[i]) for r in rows])
        except (ValueError, IndexError):
            continue
    return out if "vrad" in out and "rjd" in out else None


def sources(data_dir: str) -> dict:
    """The files a mosaic is drawn from: rdb tables, templates, one lblrv."""
    rdbs = sorted(glob.glob(os.path.join(data_dir, "lblrdb", "lbl_*.rdb")),
                  key=os.path.getmtime, reverse=True)[:12]
    tpls = sorted(glob.glob(os.path.join(data_dir, "templates",
                                         "LBL_Template_*.fits")),
                  key=os.path.getmtime, reverse=True)[:3]
    lblrv = sorted(glob.glob(os.path.join(data_dir, "lblrv", "*",
                                          "*_lbl.fits")))[:1]
    return dict(rdb=rdbs, templates=tpls, lblrv=lblrv)


def theme_of(theme) -> str:
    return theme if theme in THEMES else "light"


def key_of(found: dict, theme: str = "light") -> str:
    parts = [theme_of(theme)]
    for paths in found.values():
        for path in paths:
            try:
                parts.append("%s:%d" % (path, int(os.path.getmtime(path))))
            except OSError:
                pass
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def path_of(data_dir: str, theme: str = "light"):
    """The mosaic of this folder as it stands, in this theme, drawn or not:
    (path, ready), or (None, False) when the folder has nothing of LBL's to
    draw."""
    found = sources(data_dir)
    if not found["rdb"] and not found["templates"]:
        return None, False
    path = os.path.join(HOME, "%s.png" % key_of(found, theme))
    return path, os.path.exists(path)


def ensure(data_dir: str, theme: str = "light"):
    """Start drawing this folder's mosaic if it is not drawn yet; returns
    (path, ready)."""
    path, ready = path_of(data_dir, theme)
    if path is None or ready:
        return path, ready
    with _lock:
        if path in _running:
            return path, False
        _running.add(path)

    def work():
        try:
            draw(sources(data_dir), path, theme)
        finally:
            with _lock:
                _running.discard(path)
    threading.Thread(target=work, daemon=True).start()
    return path, False


def _tiles(found: dict) -> list:
    """The tiles, as (kind, data): one per figure the folder can give."""
    tiles = []
    tables = []
    for path in found["rdb"]:
        try:
            table = _rdb(path)
        except OSError:
            table = None
        if table is not None and len(table["vrad"]) >= 8:
            tables.append(table)
    for table in tables:
        tiles.append(("series", table))
    for table in tables[:4]:
        if "BERV" in table:
            tiles.append(("berv", table))
        tiles.append(("periodogram", table))
        for column in ("d2v", "DTEMP3500"):
            if column in table:
                tiles.append(("indicator", (table, column)))
                break
    for path in found["templates"]:
        try:
            from astropy.table import Table
            tpl = Table.read(path, "TEMPLATE")
            wave = np.asarray(tpl["wavelength"], dtype=float)
            flux = np.asarray(tpl["flux"], dtype=float)
            tiles.append(("template", (wave, flux)))
        except Exception:                                 # noqa: BLE001
            continue
    for path in found["lblrv"]:
        try:
            from astropy.io import fits
            lines = fits.getdata(path, 1)
            tiles.append(("lines", (np.asarray(lines["WAVE_START"], float),
                                    np.asarray(lines["dv"], float),
                                    np.asarray(lines["sdv"], float))))
        except Exception:                                 # noqa: BLE001
            continue
    # mixed rather than grouped, and as many as the mosaic holds
    rng = np.random.default_rng(len(tiles))
    order = rng.permutation(len(tiles))
    return [tiles[i] for i in order][:COLUMNS * ROWS]


def _draw_tile(ax, kind, data, colour):
    if kind == "series":
        t, v, e = data["rjd"], data["vrad"], data.get("svrad")
        v = v - np.nanmedian(v)
        ax.errorbar(t, v, yerr=e, fmt="o", ms=9, lw=2.5, color=colour,
                    ecolor=colour, alpha=0.95)
    elif kind == "berv":
        v = data["vrad"] - np.nanmedian(data["vrad"])
        ax.plot(data["BERV"], v, "o", ms=10, color=colour, alpha=0.95)
    elif kind == "periodogram":
        from astropy.timeseries import LombScargle
        t, v = data["rjd"], data["vrad"]
        good = np.isfinite(t) & np.isfinite(v)
        span = max(np.ptp(t[good]), 2.0)
        freq = np.linspace(1.0 / span, 1.0 / 1.2, 3000)
        power = LombScargle(t[good], v[good]).power(freq)
        ax.plot(1.0 / freq, power, lw=3.0, color=colour)
        ax.fill_between(1.0 / freq, power, color=colour, alpha=0.25)
        ax.set_xscale("log")
    elif kind == "indicator":
        table, column = data
        y = table[column] - np.nanmedian(table[column])
        ax.plot(table["rjd"], y, "s", ms=9, color=colour, alpha=0.95)
    elif kind == "template":
        wave, flux = data
        good = np.isfinite(wave) & np.isfinite(flux)
        wave, flux = wave[good], flux[good]
        if len(wave) > 2000:
            start = len(wave) // 2
            wave, flux = wave[start:start + 1500], flux[start:start + 1500]
        if len(wave) > 600:
            middle = len(wave) // 2
            wave, flux = wave[middle - 300:middle + 300], \
                flux[middle - 300:middle + 300]
        norm = flux / np.nanpercentile(flux, 95)
        ax.plot(wave, norm, lw=2.6, color=colour)
        ax.fill_between(wave, norm, np.nanmin(norm), color=colour,
                        alpha=0.18)
    elif kind == "lines":
        wave, dv, sdv = data
        good = np.isfinite(dv) & np.isfinite(sdv) & (sdv > 0)
        good &= np.abs(dv - np.nanmedian(dv[good])) < 5 * np.nanmedian(
            sdv[good])
        ax.scatter(wave[good], dv[good], s=14, color=colour, alpha=0.5,
                   linewidths=0)


def draw(found: dict, path: str, theme: str = "light") -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colours = THEMES[theme_of(theme)]
    tiles = _tiles(found)
    if not tiles:
        return
    fig = plt.figure(figsize=(WIDTH / 100, HEIGHT / 100), dpi=100,
                     facecolor=colours["page"])
    grid = fig.add_gridspec(ROWS, COLUMNS, left=0.01, right=0.99, bottom=0.02,
                            top=0.98, wspace=0.12, hspace=0.16)
    for index in range(ROWS * COLUMNS):
        kind, data = tiles[index % len(tiles)]
        ax = fig.add_subplot(grid[index // COLUMNS, index % COLUMNS])
        ax.set_facecolor(colours["tile"])
        for spine in ax.spines.values():
            spine.set_color(colours["spine"])
            spine.set_linewidth(2)
        # no numbers: blurred, they would only be noise
        ax.tick_params(colors=colours["tick"], length=2, labelbottom=False,
                       labelleft=False)
        ax.grid(color=colours["grid"], lw=1.6)
        series = colours["series"]
        try:
            _draw_tile(ax, kind, data, series[index % len(series)])
        except Exception:                                 # noqa: BLE001
            ax.set_visible(False)
    os.makedirs(HOME, exist_ok=True)
    tmp = path + ".tmp.png"
    fig.savefig(tmp, facecolor=colours["page"])
    plt.close(fig)
    os.replace(tmp, path)
    drawn = sorted(glob.glob(os.path.join(HOME, "*.png")),
                   key=os.path.getmtime, reverse=True)
    for old in drawn[KEEP:]:
        try:
            os.remove(old)
        except OSError:
            pass
