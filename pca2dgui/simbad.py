"""A target's effective temperature from SIMBAD, for the LBL tab: the
median of the Teff that SIMBAD's mesFe_H table holds for the star, those far
from its spectral type's left out, else its spectral type's (Pecaut &
Mamajek 2013). The answers are kept in DATA_DIR/gui/simbad_teff.json, one
question per target until asked again.

A target's name is its folder's, as APERO writes it ('-' as M, ' ' as _:
TOIM4508, GJ_1028); SIMBAD is asked that name, then the OBJECT of its
headers, then both as SIMBAD writes them, until one is known.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import statistics
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

TAP = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"
UA = {"User-Agent": "lbl-gui (SIMBAD Teff for LBL's OBJECT_TEFF)"}
#: where the answers are kept, in the data folder
CACHE = os.path.join("gui", "simbad_teff.json")
#: a measurement this far from its spectral type's Teff is left out (a
#:   catalogue's 4500 K for an M4.5V, 3000 K from its own paper)
SPT_TOLERANCE = 0.20
#: the questions asked at once
WORKERS = 4
#: a dwarf's Teff by spectral type [K]: Pecaut & Mamajek (2013, ApJS 208,
#:   9), Mamajek's table of 2022.04.16 (as koloa.stars.SPT_TEFF)
SPT_TEFF = [
    ('O3V', 44900), ('O4V', 42900), ('O5V', 41400), ('O5.5V', 40500),
    ('O6V', 39500), ('O6.5V', 38300), ('O7V', 37100), ('O7.5V', 36100),
    ('O8V', 35100), ('O8.5V', 34300), ('O9V', 33300), ('O9.5V', 31900),
    ('B0V', 31400), ('B0.5V', 29000), ('B1V', 26000), ('B1.5V', 24500),
    ('B2V', 20600), ('B2.5V', 18500), ('B3V', 17000), ('B4V', 16400),
    ('B5V', 15700), ('B6V', 14500), ('B7V', 14000), ('B8V', 12300),
    ('B9V', 10700), ('B9.5V', 10400), ('A0V', 9700), ('A1V', 9300),
    ('A2V', 8800), ('A3V', 8600), ('A4V', 8250), ('A5V', 8100),
    ('A6V', 7910), ('A7V', 7760), ('A8V', 7590), ('A9V', 7400),
    ('F0V', 7220), ('F1V', 7020), ('F2V', 6820), ('F3V', 6750),
    ('F4V', 6670), ('F5V', 6550), ('F6V', 6350), ('F7V', 6280),
    ('F8V', 6180), ('F9V', 6050), ('F9.5V', 5990), ('G0V', 5930),
    ('G1V', 5860), ('G2V', 5770), ('G3V', 5720), ('G4V', 5680),
    ('G5V', 5660), ('G6V', 5600), ('G7V', 5550), ('G8V', 5480),
    ('G9V', 5380), ('K0V', 5270), ('K1V', 5170), ('K2V', 5100),
    ('K3V', 4830), ('K4V', 4600), ('K5V', 4440), ('K6V', 4300),
    ('K7V', 4100), ('K8V', 3990), ('K9V', 3930), ('M0V', 3850),
    ('M0.5V', 3770), ('M1V', 3660), ('M1.5V', 3620), ('M2V', 3560),
    ('M2.5V', 3470), ('M3V', 3430), ('M3.5V', 3270), ('M4V', 3210),
    ('M4.5V', 3110), ('M5V', 3060), ('M5.5V', 2930), ('M6V', 2810),
    ('M6.5V', 2740), ('M7V', 2680), ('M7.5V', 2630), ('M8V', 2570),
    ('M8.5V', 2420), ('M9V', 2380), ('M9.5V', 2350), ('L0V', 2270),
    ('L1V', 2160), ('L2V', 2060)]
CLASSES = "OBAFGKML"

_lock = threading.Lock()


def spectral_code(sptype):
    """A dwarf's spectral type as a number (B0 10, M0 60, the subclass
    after); None for a giant, a subgiant, a white dwarf or what does not
    read ('M3.5Ve' 63.5, 'dM2' 62)."""
    if not sptype:
        return None
    text = re.sub(r"^(sd|d)", "", str(sptype).strip())
    match = re.match(r"([OBAFGKML])\s*([0-9](?:\.[0-9]+)?)?\s*"
                     r"((?:I{1,3}|IV|V|VI)?)", text)
    if not match or text.startswith(("D", "W")):
        return None
    if match.group(3) and match.group(3) not in ("V", "VI"):
        return None
    sub = float(match.group(2)) if match.group(2) else 5.0
    return CLASSES.index(match.group(1)) * 10 + sub


def teff_of_type(sptype):
    """A dwarf's Teff from its spectral type, interpolated [K], or None."""
    code = spectral_code(sptype)
    if code is None:
        return None
    table = [(spectral_code(spt), teff) for spt, teff in SPT_TEFF]
    if code < table[0][0] - 1 or code > table[-1][0] + 1:
        return None
    for (c0, t0), (c1, t1) in zip(table, table[1:]):
        if c0 <= code <= c1:
            return t0 + (t1 - t0) * (code - c0) / (c1 - c0)
    return float(table[0][1] if code < table[0][0] else table[-1][1])


def candidates(name, header_object=None):
    """The names SIMBAD is asked, in order: the folder's, its headers'
    OBJECT, then both as SIMBAD writes them (APERO's M for '-' between
    characters and digits, _ for a space, Gliese as GJ)."""
    out = []
    for raw in (name, header_object):
        if not raw:
            continue
        raw = str(raw).strip()
        spelled = re.sub(r"(?<=[A-Za-z0-9])M(?=\d)", "-", raw)
        spelled = re.sub(r"_+", " ", spelled).strip()
        spelled = re.sub(r"^gliese\s*", "GJ ", spelled, flags=re.I)
        for one in (raw, spelled):
            if one and one not in out:
                out.append(one)
    return out


def _tap(query):
    data = urllib.parse.urlencode(dict(request="doQuery", lang="adql",
                                       format="json", query=query)).encode()
    request = urllib.request.Request(TAP, data=data, headers=UA)
    with urllib.request.urlopen(request, timeout=30) as response:
        table = json.load(response)
    names = [column["name"] for column in table["metadata"]]
    return [dict(zip(names, row)) for row in table["data"]]


def summarise(main, sptype, measured):
    """The answer for a star SIMBAD knows: its measurements' median, those
    more than SPT_TOLERANCE from its spectral type's Teff left out (all of
    them kept when that would leave none), else its spectral type's."""
    out = dict(state="done", main=main, sptype=sptype, teff=None, n=0,
               n_all=len(measured), source=None)
    typed = teff_of_type(sptype)
    kept = measured
    if typed and measured:
        near = [t for t in measured if abs(t - typed) <= SPT_TOLERANCE * typed]
        kept = near or measured
    if kept:
        out.update(teff=round(statistics.median(kept) / 10.0) * 10,
                   n=len(kept), source="mesFe_H")
    elif typed:
        out.update(teff=round(typed / 10.0) * 10, source="sptype")
    return out


def ask(name, header_object=None):
    """One target, as SIMBAD knows it: dict(state done/unknown/failed, main,
    sptype, teff, n (measurements kept), n_all, source mesFe_H/sptype,
    asked, error)."""
    names = candidates(name, header_object)
    try:
        for one in names:
            quoted = one.replace("'", "''")
            rows = _tap("SELECT b.main_id, b.sp_type, m.teff FROM ident AS i"
                        " JOIN basic AS b ON b.oid = i.oidref LEFT JOIN"
                        " mesFe_h AS m ON m.oidref = b.oid WHERE i.id = '%s'"
                        % quoted)
            if rows:
                measured = [float(r["teff"]) for r in rows if r["teff"]]
                out = summarise(str(rows[0]["main_id"]).strip(),
                                rows[0]["sp_type"], measured)
                out["main"] = re.sub(r"\s+", " ", out["main"])
                out["asked"] = one
                return out
    except Exception as exc:                              # noqa: BLE001
        return dict(state="failed", error="%s: %s" % (type(exc).__name__,
                                                      str(exc)[:160]))
    return dict(state="unknown", asked=names)


def _read(data_dir):
    path = os.path.join(data_dir, CACHE)
    try:
        with open(path) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def teffs(data_dir, targets, refresh=False):
    """{name: answer} of the targets [dict(name, object)], from the folder's
    record when it has them (unless refresh), from SIMBAD otherwise; a
    failed question is not kept, so that it is asked again."""
    with _lock:
        known = _read(data_dir)
    todo = [t for t in targets if refresh or t["name"] not in known]
    if todo:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            answers = list(pool.map(lambda t: ask(t["name"], t.get("object")),
                                    todo))
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        with _lock:
            known = _read(data_dir)
            for target, answer in zip(todo, answers):
                answer["when"] = stamp
                if answer["state"] != "failed":
                    known[target["name"]] = answer
                else:
                    known.pop(target["name"], None)
            path = os.path.join(data_dir, CACHE)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                json.dump(known, handle, indent=1)
        failed = {t["name"]: a for t, a in zip(todo, answers)
                  if a["state"] == "failed"}
    else:
        failed = {}
    return {t["name"]: failed.get(t["name"]) or known.get(t["name"])
            for t in targets}
