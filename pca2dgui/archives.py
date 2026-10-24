"""The spectra of a star in the public archives, for LBL: searched and
fetched through koloa (github.com/eartigau/koloa, koloa.lblrun), which
knows where each instrument's LBL-readable spectra are:

    SPIROU    the CADC, APERO's t.fits (LBL's SPIROU CADC)
    NIRPS     ESO, the S2D with ESO's telluric model (NIRPS_HE/HA ESO)
    HARPS     ESO, the e2ds of its DRS, the blaze of each night made from
              the spectra (ESO does not give it; HARPS ORIG)
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
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

#: the instruments asked, in the order the window shows them
INSTRUMENTS = ("SPIROU", "NIRPS", "HARPS", "HARPSN", "SOPHIE", "ESPRESSO")
#: each instrument's archive and the product LBL reads, said shortly (koloa's
#:    own description is an English sentence)
ARCHIVE_NAMES = dict(SPIROU="CADC · APERO t.fits", NIRPS="ESO · S2D + tellu",
                     HARPS="ESO · DRS e2ds",
                     HARPSN="TNG (IA2) · S2D_A", SOPHIE="OHP · e2ds",
                     ESPRESSO="ESO · S2D_A")
#: what koloa keeps while it searches (the TNG's exposures of a star...)
ROOT = os.path.expanduser("~/.lbl_pca2d_gui/archives")
#: what a fetched folder came from, beside its spectra (LBL reads *.fits)
ARCHIVE_FILE = ".lbl_archive.json"
#: the files fetched at once
WORKERS = 4
#: the lines of the search's and fetch's log kept, and those the page gets
LOG_KEEP, LOG_SENT = 2000, 400
#: the window's archives, which koloa's own lines go to while it works
_SINK = None
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _hook_koloa():
    """koloa prints its lines (koloa.log._say): they go to the window's log
    too, since they say what an archive is doing while it is slow."""
    try:
        from koloa import log as klog
    except Exception:                                     # noqa: BLE001
        return
    if getattr(klog, "_lbl_gui_hooked", False):
        return
    said = klog._say

    def both(line):
        said(line)
        if _SINK is not None:
            text = _ANSI.sub("", str(line)).strip()
            # koloa's own 'YYMMDD HH:MM:SS.SS | ' stamp: the log has its own
            text = re.sub(r"^\d{6} \d\d:\d\d:\d\d(\.\d+)? \| ", "", text)
            if text:
                _SINK.say("koloa: " + text)
    klog._say = both
    klog._lbl_gui_hooked = True


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
        global _SINK
        self.lock = threading.Lock()
        self.search = dict(state="idle")
        self.fetch = dict(state="idle")
        self._groups = {}
        self._stop = False
        #: each search's number: a search stopped, or replaced by another,
        #:    has its late answers dropped
        self._search_id = 0
        self.log = []
        _SINK = self

    def say(self, text: str, level: str = "info") -> None:
        """One line of the log the page shows under the search."""
        line = dict(t=datetime.datetime.now().strftime("%H:%M:%S"),
                    level=level, text=str(text))
        with self.lock:
            self.log.append(line)
            del self.log[:-LOG_KEEP]

    # -- searching -----------------------------------------------------------
    def start_search(self, target: str, instruments, data_dir: str) -> dict:
        target = str(target or "").strip()
        instruments = [i for i in (instruments or INSTRUMENTS)
                       if i in INSTRUMENTS]
        with self.lock:
            if self.search.get("state") == "running":
                return self.status()
            self._search_id += 1
            number = self._search_id
            self.search = dict(state="running", target=target, main=None,
                               teff=None, error=None,
                               instruments={i: dict(state="searching")
                                            for i in instruments},
                               groups=[], started=time.time())
            self._groups = {}
        self.say("search: %s, in %s" % (target, ", ".join(instruments)))
        threading.Thread(target=self._search, args=(target, instruments,
                                                    data_dir, number),
                         daemon=True).start()
        return self.status()

    def stop_search(self) -> dict:
        """Stop waiting for the archives: what has answered stays, what has
        not is marked stopped, and its late answer is dropped (a thread
        waiting on an archive cannot be killed, it is only no longer
        listened to)."""
        with self.lock:
            if self.search.get("state") != "running":
                return self.status()
            self._search_id += 1
            waiting = [i for i, about in self.search["instruments"].items()
                       if about.get("state") == "searching"]
            for inst in waiting:
                self.search["instruments"][inst] = dict(state="stopped")
            self.search["state"] = "done"
        self.say("search stopped%s" % (
            ": no answer waited for from " + ", ".join(waiting) if waiting
            else ""), "warn")
        return self.status()

    def _current(self, number) -> bool:
        with self.lock:
            return number == self._search_id

    def _search(self, target, instruments, data_dir, number):
        _hook_koloa()
        why = available()
        if why:
            with self.lock:
                self.search.update(state="failed", error=why)
            self.say("koloa cannot be used: %s" % why, "error")
            return
        from koloa import lblrun
        try:
            ident = lblrun._ident(target)
        except Exception as exc:                          # noqa: BLE001
            with self.lock:
                self.search.update(state="failed", error="%s: %s" % (
                    type(exc).__name__, exc))
            self.say("SIMBAD does not know %s: %s" % (target, exc), "error")
            return
        teff = None
        try:
            from koloa.stars import stellar_teff
            teff = stellar_teff(ident).get("teff")
        except Exception:                                 # noqa: BLE001
            pass
        with self.lock:
            self.search.update(main=ident.get("main") or target, teff=teff)
        self.say("SIMBAD: %s is %s%s" % (
            target, ident.get("main") or target,
            ", Teff %.0f K" % teff if teff else ""))
        os.makedirs(ROOT, exist_ok=True)

        def one(inst):
            label = lblrun.INSTRUMENTS[inst]["label"]
            self.say("%s: asking %s" % (label, ARCHIVE_NAMES.get(inst, inst)))
            tick = time.time()
            try:
                found = lblrun.groups(target, inst, ROOT, ident)
            except Exception as exc:                      # noqa: BLE001
                if not self._current(number):
                    return
                with self.lock:
                    self.search["instruments"][inst] = dict(
                        state="failed", error=str(exc)[:200])
                self.say("%s: no answer after %.0f s: %s" % (
                    label, time.time() - tick, str(exc)[:200]), "error")
                return
            if not self._current(number):
                self.say("%s: answered after the search was stopped, %.0f s;"
                         " not kept" % (label, time.time() - tick), "warn")
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
            if rows:
                for r in rows:
                    self.say("%s: %d spectra (%s %s), %d already here, %.0f MB"
                             " to fetch into science/%s, in %.0f s" % (
                                 label, r["n"], r["lbl"], r["source"],
                                 r["have"], r["size_mb"], r["folder"],
                                 time.time() - tick))
            else:
                self.say("%s: no public spectrum LBL reads, %.0f s" % (
                    label, time.time() - tick))

        with ThreadPoolExecutor(max_workers=len(instruments) or 1) as pool:
            list(pool.map(one, instruments))
        if not self._current(number):
            return
        with self.lock:
            self.search["groups"].sort(key=lambda r: (
                INSTRUMENTS.index(r["inst"]), r["id"]))
            self.search["state"] = "done"
            took = time.time() - self.search.get("started", time.time())
        self.say("search done in %.0f s" % took)

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
            # one bar per group: what it is, where, how far
            bars = [dict(label=r["label"], folder=r["folder"],
                         total=r["n"] - r["have"], done=0, failed=0)
                    for r, _ in groups]
            self.fetch = dict(state="running", total=total, done=0,
                              failed=0, why="", current="", folders=[],
                              bars=bars)
            self._stop = False
        threading.Thread(target=self._fetch, args=(data_dir, groups,
                                                   self.search.get("teff"),
                                                   self.search.get("target")),
                         daemon=True).start()
        return self.status()

    def stop_fetch(self) -> None:
        self._stop = True
        self.say("fetch: stopping after the files under way", "warn")

    def _fetch(self, data_dir, groups, teff, target):
        calib = os.path.join(data_dir, "calib")
        os.makedirs(calib, exist_ok=True)
        for index, (row, group) in enumerate(groups):
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

            with self.lock:
                self.fetch["bars"][index].update(folder=row["folder"],
                                                 total=len(todo))
            self.say("fetch: %d %s spectra into science/%s (%d already"
                     " there)" % (len(todo), row["label"], row["folder"],
                                  len(group["spectra"]) - len(todo)))

            def get(one, science=science, group=group, index=index):
                if self._stop:
                    return "stopped"
                try:
                    why = group["get"](one, science, calib)
                except Exception as exc:                  # noqa: BLE001
                    why = "%s: %s" % (type(exc).__name__, exc)
                with self.lock:
                    bar = self.fetch["bars"][index]
                    self.fetch["done"] += 1
                    bar["done"] += 1
                    if why:
                        self.fetch["failed"] += 1
                        bar["failed"] += 1
                        self.fetch["why"] = str(why)[:200]
                    done, total = bar["done"], bar["total"]
                if why and why != "stopped":
                    self.say("%s: %s not fetched: %s" % (
                        row["label"], one["name"], str(why)[:200]), "warn")
                # one line every tenth of the way, and the last
                elif total and (done == total
                                or done % max(1, total // 10) == 0):
                    self.say("%s: %d of %d fetched" % (row["label"], done,
                                                       total))
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
            done, failed = self.fetch["done"], self.fetch["failed"]
        self.say("fetch %s: %d spectra, %d not fetched" % (
            "stopped" if self._stop else "done", done - failed, failed),
            "warn" if self._stop or failed else "info")

    def status(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(dict(search=self.search,
                                              fetch=self.fetch,
                                              log=self.log[-LOG_SENT:],
                                              koloa=available())))
