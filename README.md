# lbl-gui

A browser window for running [LBL](https://github.com/njcuk9999/lbl), with or
without the PCA2D precleaning (LBL's `lbl-pca2d` branch): pick the targets of
a data folder, set LBL and PCA2D, run, and follow the run as it goes.

The window does not compute anything itself. It writes an ordinary LBL wrap
(`wrap.py`, which also runs by hand as it is) for the targets and options
picked, runs it with the Python of the environment LBL is installed in, one
run at a time, and shows its log live. Everything it offers is read from
LBL: the instruments and data sources, the PCA2D options with their defaults
and descriptions, the observer bases already made. An option added to LBL
shows up in the window without a change here.

## What is where

| screen | what it does |
|---|---|
| Targets | the folders of `DATA_DIR/science/`, read from their headers (spectra, nights, SNR, BERV range, dates, Teff), with the BERV coverage, SNR against BERV and the dates of the ticked ones |
| LBL settings | the template of each target (its own or another star's), its temperature, and LBL's steps |
| PCA2D settings | the precleaning on or off, and its options: the fit, the observer bases (a frozen one, or saving this fit's), the correction |
| Run | the wrap as it will run with what is ticked upstream (it can be edited and saved), loading a wrap, the queue, and the live log of a run |
| Runs | the runs of the window, the PCA2D fits on disk and LBL's reports, read back from the data folder |
| Cleanup | what the products weigh, by what deleting them costs; only what can be made again can be deleted, and nothing while a run works in the folder |

The code is a small standard-library server (`pca2dgui/app.py`) and one
page (`pca2dgui/static/`):

| file | what |
|---|---|
| `lblinfo.py` | what the window reads from LBL |
| `targets.py` | the header scan, kept in `~/.lbl_pca2d_gui/scans/` |
| `wrapgen.py` | from the window's state to the run parameters, checked, and the wrap |
| `wrapload.py` | a wrap read back into the window (parsed, never run) |
| `backdrop.py` | the background: a mosaic of the data folder's own LBL results |
| `runner.py` | the queue, the runs and their logs |
| `history.py`, `cleanup.py` | the Runs and Cleanup screens |
| `i18n.py` | the words, in English and French |

A wrap can be loaded (Run): it is parsed, never executed, its literal
values fill the tabs, and whatever the window does not lay out (INPUT_FILE,
a PCA2D `section.key`...) is kept and written back into every wrap made from
it, so that a wrap loaded and saved again loses nothing.

The background is drawn from the data folder itself: its velocity curves,
periodograms, indicators, a template and one exposure's per-line
velocities, blurred behind the cards (cached in `~/.lbl_pca2d_gui/`, the
last few only).

The window is light by default, with a dark theme a click away in the
banner; both use the shared fonts and banner of eartigau's tools, and each
has its own validated colour palette for the plots.

Each run leaves `DATA_DIR/gui/runs/<run>/`: its `wrap.py`, its log
(`run.log`), and `run.json` (what ran, when, how it ended, the reports it
wrote). A run does not depend on the window: closing it leaves the run
going, and opening it again on the same data folder finds it, and the runs
still queued.

## Install

The window runs in the conda environment LBL (`lbl-pca2d` branch) is
installed in, since that is where it reads LBL from and what runs the
wraps:

```
conda activate lbl-pca2d
git clone <this repository> lbl-pca2d-gui
pip install -e lbl-pca2d-gui
```

It needs nothing LBL does not already need (numpy, astropy, pyyaml).

## Use

```
lbl-gui                                  # opens the window in the browser
lbl-gui --data-dir ~/lbl-pca2d-demo      # on this data folder
lbl-gui --port 8800 --no-browser         # another port, no browser
```

`pca2d-gui` is the same command, under its first name.

The window listens on the local machine only (`127.0.0.1`) and serves files
from the data folders it is given only. What it remembers between sessions
(the data folder, the ticked targets, the options) is in
`~/.lbl_pca2d_gui.json`.

## Tests

```
pytest tests
```
