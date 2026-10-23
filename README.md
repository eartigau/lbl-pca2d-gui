# pca2d-gui

A browser window for running [LBL](https://github.com/njcuk9999/lbl) with
the PCA2D precleaning (LBL's `lbl-pca2d` branch): pick the targets of a data
folder, set the options, run, and follow the run as it goes.

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
| Settings | the PCA2D options (the fit, the observer bases, the correction), the template of each target (its own or another star's), and LBL's steps |
| Run | the wrap as it will run (it can be edited), the queue, and the live log of a run |
| Runs | the runs of the window, the PCA2D fits on disk and LBL's reports, read back from the data folder |
| Cleanup | what the products weigh, by what deleting them costs; only what can be made again can be deleted, and nothing while a run works in the folder |

The code is a small standard-library server (`pca2dgui/app.py`) and one
page (`pca2dgui/static/`):

| file | what |
|---|---|
| `lblinfo.py` | what the window reads from LBL |
| `targets.py` | the header scan, kept in `~/.lbl_pca2d_gui/scans/` |
| `wrapgen.py` | from the window's state to the run parameters, checked, and the wrap |
| `runner.py` | the queue, the runs and their logs |
| `history.py`, `cleanup.py` | the Runs and Cleanup screens |
| `i18n.py` | the words, in English and French |

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
pca2d-gui                                # opens the window in the browser
pca2d-gui --data-dir ~/lbl-pca2d-demo    # on this data folder
pca2d-gui --port 8800 --no-browser       # another port, no browser
```

The window listens on the local machine only (`127.0.0.1`) and serves files
from the data folders it is given only. What it remembers between sessions
(the data folder, the ticked targets, the options) is in
`~/.lbl_pca2d_gui.json`.

## Tests

```
pytest tests
```
