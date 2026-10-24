"""The runs of a data folder, read back from disk, never remembered by the
window: what the window ran (DATA_DIR/gui/runs/*/run.json), the PCA2D
corrections on disk (DATA_DIR/pca2d/**/resolved_config.yaml, the record
lbl_pca2d writes with every fit) and LBL's reports (DATA_DIR/reports/*.pdf).
A run made from a terminal shows up as well as one made from the window.
"""
from __future__ import annotations

import glob
import json
import os

#: where the window keeps its runs, under DATA_DIR
GUI_RUNS = os.path.join("gui", "runs")


def window_runs(data_dir: str) -> list:
    out = []
    for path in glob.glob(os.path.join(data_dir, GUI_RUNS, "*", "run.json")):
        try:
            with open(path) as handle:
                record = json.load(handle)
        except (OSError, ValueError):
            continue
        record["folder"] = os.path.dirname(path)
        record["log"] = os.path.join(record["folder"], "run.log")
        out.append(record)
    out.sort(key=lambda r: r.get("created") or 0, reverse=True)
    return out


def reports(data_dir: str) -> list:
    """LBL's reports: dict(name, path, mtime, size)."""
    out = []
    for path in glob.glob(os.path.join(data_dir, "reports", "*.pdf")):
        try:
            stat = os.stat(path)
        except OSError:
            continue
        out.append(dict(name=os.path.basename(path), path=path,
                        mtime=stat.st_mtime, size=stat.st_size))
    out.sort(key=lambda r: r["mtime"], reverse=True)
    return out
