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


def pca2d_runs(data_dir: str) -> list:
    """Every PCA2D fit on disk but the superseded ones: dict(object, tag,
    folder, hash, started, command, report, settings)."""
    import yaml
    out = []
    root = os.path.join(data_dir, "pca2d")
    for path in glob.glob(os.path.join(root, "**", "resolved_config.yaml"),
                          recursive=True):
        if "/superseded/" in path or "/cache/" in path:
            continue
        folder = os.path.dirname(path)
        try:
            with open(path) as handle:
                config = yaml.safe_load(handle) or {}
        except (OSError, yaml.YAMLError):
            continue
        provenance = config.get("provenance") or {}
        twoframe = config.get("twoframe") or {}
        pdfs = sorted(glob.glob(os.path.join(folder, "*.pdf")))
        out.append(dict(
            object=(config.get("input") or {}).get("object")
            or os.path.basename(os.path.dirname(folder)),
            tag=os.path.basename(folder), folder=folder,
            hash=provenance.get("run_hash"),
            started=str(provenance.get("started", "")),
            command=provenance.get("command"),
            commit=provenance.get("commit"),
            components=[twoframe.get("n_star"), twoframe.get("n_earth")],
            basis=basis_label(twoframe.get("earth_basis")),
            report=pdfs[-1] if pdfs else None,
            mtime=os.path.getmtime(path)))
    out.sort(key=lambda r: r["mtime"], reverse=True)
    return out


def basis_label(path):
    """A frozen basis by its name (PCA2D_Observer_<name>_<instrument>.fits)
    rather than its path"""
    if not path:
        return None
    name = os.path.basename(str(path))
    if name.startswith("PCA2D_Observer_") and name.endswith(".fits"):
        name = name[len("PCA2D_Observer_"):-len(".fits")]
        name = name.rsplit("_", 1)[0] if "_" in name else name
        for suffix in ("_nirps", "_nirps_he", "_nirps_ha"):
            if name.endswith(suffix):
                name = name[:-len(suffix)]
    return name


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
