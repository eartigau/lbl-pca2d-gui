"""From what the window holds to an LBL wrap: the run parameters, checked,
and the wrap.py that runs them.

The wrap is the record of a run and the run itself: it is written to disk
before anything starts, runs by hand as it is, and holds nothing the window
alone could read. The PCA2D options a run leaves at their defaults are left
out of it (n_star and n_earth are written whenever they were chosen), so that
a wrap says what was chosen and the rest is LBL's nominal of the day.
"""
from __future__ import annotations

import datetime
import os
import re
import sys

from . import i18n, lblinfo

#: the PCA2D options a wrap writes whenever they are chosen, even at their
#:    default (the rest only when they differ from it); one left unchosen is
#:    not written, since its default may not be what a run uses (n_earth is
#:    the frozen basis's own count when input_name names one)
ALWAYS = ("n_star", "n_earth")
#: the temperature handed to LBL when the headers give none [K]
TEFF_FALLBACK = 3500


def _coerce(value, kind: str):
    """A value as the option's kind, from what a page sends (strings, empty
    for unset)."""
    if value is None or value == "":
        return None
    if kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if kind == "int":
        return int(float(value))
    if kind == "float":
        return float(value)
    return str(value)


#: the instruments whose spectra come telluric-corrected (APERO): LBL's
#:    telluric cleaning is always off for them
NO_TELLUCLEAN = ("NIRPS", "SPIROU")


def _family(name) -> str:
    """An instrument's family, the headers' way or LBL's: NIRPS for NIRPS,
    NIRPS_HE and NIRPS_HA, HARPSN for HARPS-N. Empty when unknown."""
    name = str(name or "").upper()
    if not name or name == "?" or "/" in name:
        return ""
    return re.sub(r"[^A-Z0-9]", "", name.split("_")[0])


def build(state: dict) -> dict:
    """The run parameters of a wrap from the window's state: dict(rparams,
    errors, warnings). Nothing is written."""
    errors, warnings = [], []
    # the window's language, for what it says (i18n's err_* and warn_*)
    words = i18n.strings(state.get("lang") or "en")

    def say(key, *args):
        return words[key] % tuple(str(a) for a in args)
    data_dir = os.path.abspath(os.path.expanduser(state.get("data_dir") or ""))
    instrument = state.get("instrument") or ""
    source = state.get("source") or "None"
    targets = [t for t in state.get("targets") or [] if t]
    if not data_dir or not os.path.isdir(data_dir):
        errors.append(say("err_no_folder", data_dir))
    if not instrument:
        errors.append(say("err_no_instrument"))
    if not targets:
        errors.append(say("err_no_target"))
    known = {row["instrument"]: row for row in lblinfo.instruments()}
    sources = {s["source"]: s for s in
               (known.get(instrument) or {}).get("sources", [])}
    if instrument and instrument not in known:
        errors.append(say("err_unknown_instrument", instrument))
    elif instrument and str(source) not in sources:
        errors.append(say("err_no_source", instrument, source,
                          ", ".join(sources)))
    # THE SPECTRA ARE THE INSTRUMENT'S: SPIRou files run as NIRPS_HE made a
    #   NIRPS template of SPIRou spectra and stopped on the first lblrv file
    #   (2026-10-23). The headers' instrument against the one chosen, by
    #   family (NIRPS for NIRPS_HE and NIRPS_HA)
    for target, header in (state.get("instruments") or {}).items():
        if target in targets and instrument and _family(header) \
                and _family(header) != _family(instrument):
            errors.append(say("err_wrong_instrument", target, header,
                              instrument))
    rparams = dict()
    rparams["INSTRUMENT"] = instrument
    rparams["DATA_SOURCE"] = source
    rparams["DATA_DIR"] = data_dir
    rparams["DATA_TYPES"] = ["SCIENCE"] * len(targets)
    rparams["OBJECT_SCIENCE"] = list(targets)
    comparison = state.get("comparison") or {}
    teff = state.get("teff") or {}
    rparams["OBJECT_COMPARISON"] = [comparison.get(t) or t for t in targets]
    teffs = []
    for target in targets:
        value = teff.get(target)
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = None
        if value is None:
            warnings.append(say("warn_no_teff", target, TEFF_FALLBACK))
            value = TEFF_FALLBACK
        teffs.append(int(round(value)))
    rparams["OBJECT_TEFF"] = teffs
    templates = {row["name"] for row in lblinfo.templates(data_dir, instrument)}
    vetted = {row["name"]: row for row in lblinfo.vetted(instrument)}
    for target, other in zip(targets, rparams["OBJECT_COMPARISON"]):
        # a vetted template comes from LBL's depot when the run needs it:
        #   one the depot does not have stops the run on its first step
        if str(other).upper().startswith("VETTED_"):
            if other not in vetted:
                errors.append(say("err_vetted_unknown", other, instrument))
                continue
            where = lblinfo.vetted_where(data_dir, vetted[other])
            if where == "missing":
                errors.append(say("err_vetted_missing", other,
                                  vetted[other]["file"],
                                  os.path.join(data_dir, "models")))
            elif where == "unknown":
                warnings.append(say("warn_vetted_unknown", other))
            continue
        if other != target and other not in templates and not os.path.isdir(
                os.path.join(data_dir, "science", other)):
            errors.append(say("err_no_comparison", target, other))
    # the LBL switches
    lbl = state.get("lbl") or {}
    telluclean = (sources.get(str(source)) or {}).get("telluclean", False)
    for row in lblinfo.lbl_switches():
        key = row["key"]
        value = lbl.get(key, row["default"])
        if key == "RUN_LBL_TELLUCLEAN" and value is None:
            value = telluclean
        # NIRPS's and SPIRou's spectra come telluric-corrected: never
        #   LBL's own cleaning on them, whatever the state says
        if key == "RUN_LBL_TELLUCLEAN" and _family(instrument) in NO_TELLUCLEAN:
            value = False
        rparams[key] = bool(value)
    if state.get("resproj"):
        rparams["RESPROJ_TABLES"] = {
            "DTEMP3500": "temperature_gradient_3500.fits"}
    # what a loaded wrap held that the window does not: written back as it
    #   was (wrapload.to_state)
    from .wrapload import MANAGED
    for key, value in (state.get("extra") or {}).items():
        if key not in MANAGED and key not in rparams:
            rparams[key] = value
    # PCA2D
    if state.get("pca2d_on", True):
        options = {row["key"]: row for row in
                   lblinfo.pca2d_options(instrument)} if instrument else {}
        chosen = state.get("pca2d") or {}
        pca2d = dict()
        for key, row in options.items():
            if key not in chosen:
                continue
            try:
                value = _coerce(chosen[key], row["kind"])
            except (TypeError, ValueError):
                errors.append(say("err_pca2d_kind", key, repr(chosen[key]),
                                  row["kind"]))
                continue
            if key in ALWAYS or value != row["default"]:
                if value is not None or row["default"] is not None:
                    pca2d[key] = value
        for key in ("min_rjd", "max_rjd"):
            value = state.get(key)
            if value not in (None, ""):
                pca2d[key] = float(value)
        for key, value in (state.get("pca2d_extra") or {}).items():
            pca2d.setdefault(key, value)
        if pca2d.get("joint") and len(targets) < 2:
            warnings.append(say("warn_joint"))
            pca2d.pop("joint")
        if pca2d.get("input_name"):
            found = [b for b in lblinfo.bases(data_dir, instrument, source)
                     if b["name"] == pca2d["input_name"]]
            if not found:
                errors.append(say("err_no_basis", pca2d["input_name"],
                                  os.path.join(data_dir, lblinfo.BASES)))
            elif not found[0]["compatible"]:
                errors.append(say("err_basis_other", pca2d["input_name"],
                                  found[0]["instrument"], found[0]["source"],
                                  instrument, source))
        try:
            from lbl.recipes import lbl_pca2d
            lbl_pca2d.settings(dict(pca2d), report=rparams.get("REPORT", True))
        except Exception as exc:                          # noqa: BLE001
            errors.append(say("err_pca2d", exc))
        rparams["PCA2D"] = pca2d
        skip = state.get("skip_pca2d")
        if skip is not None:
            rparams[lblinfo.SKIP_PCA2D] = bool(skip)
    return dict(rparams=rparams, errors=errors, warnings=warnings)


def render(rparams: dict, name: str = "", python: str = "") -> str:
    """The wrap.py of these run parameters."""
    python = python or sys.executable
    when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    targets = ", ".join(rparams.get("OBJECT_SCIENCE") or [])
    lines = [
        "#!%s" % python,
        "# -*- coding: utf-8 -*-",
        '"""',
        "%s: LBL%s on %s (%s, %s), written by the LBL window (lbl-gui)"
        " on %s."
        % (name or "run", " with the PCA2D precleaning"
           if "PCA2D" in rparams else "", targets,
           rparams.get("INSTRUMENT"), rparams.get("DATA_SOURCE"), when),
        "",
        "    %s %s" % (python, "wrap.py"),
        "",
        "It runs by hand as it is: what the window ran is all here.",
        '"""',
        "from lbl.recipes import lbl_wrap",
        "",
        'if __name__ == "__main__":',
        "    rparams = dict()",
    ]
    for key, value in rparams.items():
        if key == "PCA2D":
            continue
        lines.append("    rparams[%r] = %r" % (key, value))
    if "PCA2D" in rparams:
        lines.append("    rparams['PCA2D'] = dict(")
        for key, value in rparams["PCA2D"].items():
            lines.append("        %s=%r," % (key, value))
        lines.append("    )")
    lines.append("    lbl_wrap.main(rparams)")
    return "\n".join(lines) + "\n"


#: LBL's recipes, in the order _lbl_steps runs them, and their switch
LBL_STEPS = (("template", "RUN_LBL_TEMPLATE"), ("mask", "RUN_LBL_MASK"),
             ("compute", "RUN_LBL_COMPUTE"), ("compile", "RUN_LBL_COMPILE"))


def steps(rparams: dict) -> list:
    """The steps of a run, in the order lbl_wrap goes through them:
    [dict(kind, obj)], kind one of telluclean, template, mask, compute,
    compile, report, pca2d_cube, pca2d_fit, pca2d_figures, pca2d_correct.
    The window ticks them off as the log names them (runner.Job)."""
    out = []
    targets = list(rparams.get("OBJECT_SCIENCE") or [])
    pca2d = rparams.get("PCA2D")
    on = pca2d not in (None, False)
    pca2d = pca2d if isinstance(pca2d, dict) else {}
    compare = on and pca2d.get("compare", True)
    joint = on and pca2d.get("joint")
    figures = pca2d.get("figures", rparams.get("REPORT", True))
    name = pca2d.get("name")
    tellu = bool(rparams.get("RUN_LBL_TELLUCLEAN"))
    measured = set()

    def lbl(obj):
        for kind, switch in LBL_STEPS:
            if rparams.get(switch, True):
                out.append(dict(kind=kind, obj=obj))
        if rparams.get("REPORT", True) and rparams.get("RUN_LBL_COMPILE", True):
            out.append(dict(kind="report", obj=obj))

    fitted = False
    for target in targets:
        obj = target
        if tellu:
            out.append(dict(kind="telluclean", obj=target))
            obj = target + "_tc"
        if not on:
            lbl(obj)
            continue
        if compare and obj not in measured:
            lbl(obj)
            measured.add(obj)
        if joint and not fitted and compare and not tellu:
            for other in targets:
                if other not in measured:
                    lbl(other)
                    measured.add(other)
        if not (joint and fitted):
            stages = ("cube", "fit") + (("figures",) if figures else ()) \
                + ("correct",)
            for stage in stages:
                out.append(dict(kind="pca2d_" + stage,
                                obj="+".join(targets) if joint else obj))
            fitted = True
        lbl(obj + "_pca2d" + ("_" + name if name else ""))
    return out
