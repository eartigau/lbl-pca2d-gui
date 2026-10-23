"""The spectra of a star in the public archives, for LBL: searched and
fetched through koloa (github.com/eartigau/koloa, koloa.lblrun), which
knows where each instrument's LBL-readable spectra are:

    SPIROU    the CADC, APERO's t.fits (LBL's SPIROU CADC)
    NIRPS     ESO, the S2D with ESO's telluric model (NIRPS_HE/HA ESO)
    HARPSN    the TNG, espdr's S2D_A (HARPSN ESO)
    SOPHIE    the OHP, e2ds and their blaze (SOPHIE)
    ESPRESSO  ESO, the S2D_A (ESPRESSO)

A search asks every instrument at once (an archive that does not answer
holds the others up no more than its own time); what each one has is a
run of LBL, a group: its LBL instrument and source, its spectra. A fetch
writes a group's spectra into DATA_DIR/science/<folder>/ and its
calibrations into DATA_DIR/calib/, one file at a time through koloa's own
getters, and never moves or overwrites a file that is there (koloa's
lblrun.fetch moves aside what is not the star's: not here). The folder
then holds ARCHIVE_FILE, what it came from, which the window reads to set
the data source and the file pattern of the wrap.
"""
from __future__ import annotations

import datetime
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

#: the instruments asked, in the order the window shows them
INSTRUMENTS = ("SPIROU", "NIRPS", "HARPSN", "SOPHIE", "ESPRESSO")
#: each instrument's archive and the product LBL reads, said shortly (koloa's
#:    own description is an English sentence)
ARCHIVE_NAMES = dict(SPIROU="CADC · APERO t.fits", NIRPS="ESO · S2D + tellu",
                     HARPSN="TNG (IA2) · S2D_A", SOPHIE="OHP · e2ds",
                     ESPRESSO="ESO · S2D_A")
#: what koloa keeps while it searches (the TNG's exposures of a star...)
ROOT = os.path.expanduser("~/.lbl_pca2d_gui/archives")
#: what a fetched folder came from, beside its spectra (LBL reads *.fits)
ARCHIVE_FILE = ".lbl_archive.json"
#: the files fetched at once
WORKERS = 4


def available():
    """None if koloa can be used, else why not."""
    try:
        from koloa import lblrun                          # noqa: F401
    except Exception as exc:                              # noqa: BLE001
        return "%s: %s" % (type(exc).__name__, exc)
    return None


def provenance(folder: str):
    """What a folder of spectra was fetched from (ARCHIVE_FILE), or None."""
    try:
        with open(os.path.join(folder, ARCHIVE_FILE)) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def folder_for(data_dir: str, group: dict) -> str:
    """Where a group's spectra go: science/<object> if the folder is new or
    holds these spectra already (or came from the same LBL instrument and
    source); else science/<object>_<instrument>_<source>, so that one folder
    never mixes two readers."""
    base = group["obj"]
    names = {one["name"] for one in group["spectra"]}
    for name in (base, "%s_%s_%s" % (base, group["lbl"], group["source"])):
        path = os.path.join(data_dir, "science", name)
        if not os.path.isdir(path):
            return name
        mine = provenance(path)
        if mine and mine.get("lbl") == group["lbl"] \
                and mine.get("source") == group["source"]:
            return name
        here = {f for f in os.listdir(path) if f.endswith(".fits")}
        if not here or here <= names:
            return name
    return "%s_%s_%s" % (base, group["lbl"], group["source"])


class Archives:
    """One search and one fetch at a time, followed by the page."""

    def __init__(self):
        self.lock = threading.Lock()
        self.search = dict(state="idle")
        self.fetch = dict(state="idle")
        self._groups = {}
        self._stop = False

    # -- searching -----------------------------------------------------------
    def start_search(self, target: str, instruments, data_dir: str) -> dict:
        target = str(target or "").strip()
        instruments = [i for i in (instruments or INSTRUMENTS)
                       if i in INSTRUMENTS]
        with self.lock:
            if self.search.get("state") == "running":
                return self.status()
            self.search = dict(state="running", target=target, main=None,
                               teff=None, error=None,
                               instruments={i: dict(state="searching")
                                            for i in instruments},
                               groups=[])
            self._groups = {}
        threading.Thread(target=self._search, args=(target, instruments,
                                                    data_dir),
                         daemon=True).start()
        return self.status()

    def _search(self, target, instruments, data_dir):
        why = available()
        if why:
            with self.lock:
                self.search.update(state="failed", error=why)
            return
        from koloa import lblrun
        try:
            ident = lblrun._ident(target)
        except Exception as exc:                          # noqa: BLE001
            with self.lock:
                self.search.update(state="failed", error="%s: %s" % (
                    type(exc).__name__, exc))
            return
        teff = None
        try:
            from koloa.stars import stellar_teff
            teff = stellar_teff(ident).get("teff")
        except Exception:                                 # noqa: BLE001
            pass
        with self.lock:
            self.search.update(main=ident.get("main") or target, teff=teff)
        os.makedirs(ROOT, exist_ok=True)

        def one(inst):
            try:
                found = lblrun.groups(target, inst, ROOT, ident)
            except Exception as exc:                      # noqa: BLE001
                with self.lock:
                    self.search["instruments"][inst] = dict(
                        state="failed", error=str(exc)[:200])
                return
            size = lblrun.INSTRUMENTS[inst]["size"]
            rows = []
            for group in found:
                if not group["spectra"]:
                    continue
                key = "%s:%s" % (inst, group["key"])
                folder = folder_for(data_dir, group) if data_dir else \
                    group["obj"]
                # two readers never share a folder: one already proposed
                #   for another reader of this search gives this one its
                #   reader's name
                with self.lock:
                    taken = {r["folder"] for r in self.search["groups"]}
                if folder in taken:
                    folder = "%s_%s_%s" % (group["obj"], group["lbl"],
                                           group["source"])
                here = os.path.join(data_dir or "", "science", folder)
                have = sum(os.path.exists(os.path.join(here, s["name"]))
                           for s in group["spectra"])
                rows.append(dict(
                    id=key, inst=inst, label=lblrun.INSTRUMENTS[inst]["label"],
                    archive=ARCHIVE_NAMES.get(inst, inst),
                    lbl=group["lbl"], source=group["source"],
                    input=group["input"], params=group["params"],
                    n=len(group["spectra"]), have=have, folder=folder,
                    size_mb=round(size * (len(group["spectra"]) - have), 1)))
                with self.lock:
                    self._groups[key] = group
            with self.lock:
                self.search["instruments"][inst] = dict(
                    state="done", n=sum(r["n"] for r in rows))
                self.search["groups"] += rows

        with ThreadPoolExecutor(max_workers=len(instruments) or 1) as pool:
            list(pool.map(one, instruments))
        with self.lock:
            self.search["groups"].sort(key=lambda r: (
                INSTRUMENTS.index(r["inst"]), r["id"]))
            self.search["state"] = "done"

    # -- fetching ------------------------------------------------------------
    def start_fetch(self, data_dir: str, ids) -> dict:
        with self.lock:
            if self.fetch.get("state") == "running":
                return self.status()
            rows = [r for r in self.search.get("groups", []) if r["id"] in ids]
            groups = [(r, self._groups[r["id"]]) for r in rows
                      if r["id"] in self._groups]
            if not groups:
                return dict(self.status(), error="nothing chosen")
            total = sum(r["n"] - r["have"] for r, _ in groups)
            self.fetch = dict(state="running", total=total, done=0,
                              failed=0, why="", current="", folders=[])
            self._stop = False
        threading.Thread(target=self._fetch, args=(data_dir, groups,
                                                   self.search.get("teff"),
                                                   self.search.get("target")),
                         daemon=True).start()
        return self.status()

    def stop_fetch(self) -> None:
        self._stop = True

    def _fetch(self, data_dir, groups, teff, target):
        calib = os.path.join(data_dir, "calib")
        os.makedirs(calib, exist_ok=True)
        for row, group in groups:
            # asked again: a group fetched just before may have taken it
            mine = provenance(os.path.join(data_dir, "science", row["folder"]))
            if mine and (mine.get("lbl"), mine.get("source")) != (
                    row["lbl"], row["source"]):
                row["folder"] = "%s_%s_%s" % (group["obj"], row["lbl"],
                                              row["source"])
            science = os.path.join(data_dir, "science", row["folder"])
            os.makedirs(science, exist_ok=True)
            with self.lock:
                self.fetch["current"] = "%s %s" % (row["label"], row["folder"])
            todo = [one for one in group["spectra"]
                    if not os.path.exists(os.path.join(science, one["name"]))]

            def get(one, science=science, group=group):
                if self._stop:
                    return "stopped"
                try:
                    why = group["get"](one, science, calib)
                except Exception as exc:                  # noqa: BLE001
                    why = "%s: %s" % (type(exc).__name__, exc)
                with self.lock:
                    self.fetch["done"] += 1
                    if why:
                        self.fetch["failed"] += 1
                        self.fetch["why"] = str(why)[:200]
                return why

            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                list(pool.map(get, todo))
            with open(os.path.join(science, ARCHIVE_FILE), "w") as handle:
                json.dump(dict(target=target, inst=row["inst"],
                               lbl=row["lbl"], source=row["source"],
                               input=row["input"], params=row["params"],
                               archive=row["archive"], teff=teff,
                               fetched=datetime.datetime.now().isoformat(
                                   timespec="seconds")), handle, indent=1)
            with self.lock:
                self.fetch["folders"].append(row["folder"])
            if self._stop:
                break
        with self.lock:
            self.fetch["state"] = "stopped" if self._stop else "done"
            self.fetch["current"] = ""

    def status(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(dict(search=self.search,
                                              fetch=self.fetch,
                                              koloa=available())))
