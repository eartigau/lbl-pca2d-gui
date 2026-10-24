"""static/references.json, what the References tab shows: the paper that
describes LBL, with its BibTeX, and the papers whose velocities LBL measured
(tools/lbl_references.yaml, read paper by paper), each with the sentence
that says so. Their authors, journal, volume and page come from CrossRef
(by DOI, found with OpenAlex), else from the arXiv record.

    python tools/lbl_references.py <folder with meta/papers.json,
                                    meta/citing_biblio.json, meta/lbl_biblio.json>
"""
import datetime
import html
import json
import os
import re
import sys
import time
import urllib.request

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "..", "pca2dgui", "static")
UA = {"User-Agent": "lbl-gui-references/1.0 (personal research tool)"}
#: the instruments a paper's LBL sentences name, for the tab's filter
INSTRUMENTS = ("SPIRou", "NIRPS", "HARPS-N", "HARPS", "ESPRESSO", "CARMENES",
               "SOPHIE", "MAROON-X", "NEID", "EXPRES", "ESPaDOnS", "CORALIE",
               "IRD", "HPF", "iSHELL", "GIANO")


def get_json(url):
    time.sleep(0.5)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def crossref(doi):
    try:
        return get_json("https://api.crossref.org/works/" + doi)["message"]
    except Exception:                                      # noqa: BLE001
        return None


def authors_short(families):
    families = [f for f in families if f]
    if not families:
        return "?"
    if len(families) == 1:
        return families[0]
    if len(families) == 2:
        return "%s & %s" % tuple(families)
    return "%s et al." % families[0]


def openalex_of(arxiv, title, works):
    """The OpenAlex record of a paper: by its arXiv id, else its title"""
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())[:70]
    for w in works:
        for loc in w.get("locations") or []:
            url = (loc.get("landing_page_url") or "") + (loc.get("pdf_url") or "")
            if arxiv and arxiv in url:
                return w
    for w in works:
        if title and norm(w.get("title")) == norm(title):
            return w
    return None


def describe(arxiv, title, work, year):
    """A paper's entry: authors, year, title, journal, volume, page, DOI,
    arXiv"""
    doi = (work or {}).get("doi") or ""
    doi = doi.replace("https://doi.org/", "") or None
    # an arXiv DOI is not the journal's
    if doi and doi.lower().startswith("10.48550"):
        doi = None
    out = dict(arxiv=arxiv, doi=doi, year=year, title=title)
    meta = crossref(doi) if doi else None
    if meta:
        out["authors"] = authors_short([a.get("family") for a in meta.get("author", [])])
        out["journal"] = html.unescape((meta.get("container-title") or [""])[0])
        out["volume"] = meta.get("volume")
        out["page"] = meta.get("article-number") or meta.get("page")
        # a series' papers carry the series as title, their own as subtitle
        #   ("The GAPS Programme at TNG" alone)
        full = (meta.get("title") or [title])[0]
        if meta.get("subtitle"):
            full = "%s. %s" % (full.rstrip(". "), meta["subtitle"][0])
        out["title"] = html.unescape(re.sub(r"<[^>]+>", "", full))
        issued = (meta.get("issued") or {}).get("date-parts") or [[year]]
        out["year"] = issued[0][0] or year
    else:
        names = [(a.get("author") or {}).get("display_name") for a in (work or {}).get("authorships", [])]
        out["authors"] = authors_short([n.split()[-1] if n else n for n in names])
        out["journal"] = "arXiv preprint"
    return out


def bibtex(meta, arxiv):
    """The method's BibTeX, from CrossRef"""
    names = " and ".join("{%s}, %s" % (a["family"], a.get("given", ""))
                         for a in meta["author"])
    return "\n".join([
        "@ARTICLE{Artigau2022,",
        "       author = {%s}," % names,
        '        title = "{%s}",' % meta["title"][0],
        "      journal = {%s}," % meta["container-title"][0],
        "         year = %d," % meta["issued"]["date-parts"][0][0],
        "       volume = {%s}," % meta["volume"],
        "       number = {%s}," % meta.get("issue", ""),
        "          eid = {%s}," % (meta.get("article-number") or meta.get("page")),
        "          doi = {%s}," % meta["DOI"],
        "archivePrefix = {arXiv},",
        "       eprint = {%s}," % arxiv,
        "}"])


def main(folder):
    meta_dir = os.path.join(folder, "meta")
    papers = json.load(open(os.path.join(meta_dir, "papers.json")))
    by_arxiv = {r.get("arxiv"): r for r in papers.values() if r.get("arxiv")}
    works = json.load(open(os.path.join(meta_dir, "citing_biblio.json")))["results"]
    lbl_work = json.load(open(os.path.join(meta_dir, "lbl_biblio.json")))
    chosen = yaml.safe_load(open(os.path.join(HERE, "lbl_references.yaml")))

    method_arxiv = str(chosen["method"])
    method = describe(method_arxiv, lbl_work["title"], lbl_work,
                      lbl_work["publication_year"])
    method_meta = crossref(method["doi"])

    out, seen = [], set()
    for row in chosen["listed"]:
        # by arXiv id, or by DOI for a paper with no source on arXiv (read
        #   in its abstract)
        arxiv = str(row["arxiv"]) if row.get("arxiv") else None
        doi = str(row["doi"]) if row.get("doi") else None
        if (arxiv or doi) in seen:
            continue
        seen.add(arxiv or doi)
        rec = by_arxiv.get(arxiv) or {}
        if arxiv:
            work = openalex_of(arxiv, rec.get("title"), works)
        else:
            work = next((w for w in works if (w.get("doi") or "").lower()
                         .endswith(doi.lower())), None) or dict(
                             doi="https://doi.org/" + doi)
        entry = describe(arxiv, rec.get("title") or (work or {}).get("title"),
                         work, rec.get("year") or (work or {}).get("publication_year"))
        entry["evidence"] = row["evidence"]
        if row.get("role"):
            entry["role"] = row["role"]
        text = " ".join([entry["title"]] + rec.get("contexts", []))
        entry["instruments"] = [i for i in INSTRUMENTS
                                if re.search(r"\b%s\b" % re.escape(i), text, re.I)
                                and not (i == "HARPS" and re.search(r"HARPS-N", text)
                                         and not re.search(r"HARPS(?!-N)", text))]
        out.append(entry)
        print("%s %s %s" % (entry["year"], entry["authors"], entry["journal"]))
    out.sort(key=lambda e: (-int(e["year"] or 0), e["authors"]))

    credits = []
    path = os.path.join(STATIC, "backdrop_credits.json")
    if os.path.exists(path):
        listed = {e["arxiv"]: e for e in out + [method]}
        for c in json.load(open(path)):
            e = listed.get(c["arxiv"])
            # one line per paper, however many of its figures are used
            if e and all(k["arxiv"] != e["arxiv"] for k in credits):
                credits.append(dict(authors=e["authors"], year=e["year"],
                                    title=e["title"], doi=e.get("doi"),
                                    arxiv=e["arxiv"],
                                    licence="CC " + c["licence"].rstrip("/")
                                    .split("/licenses/")[-1].replace("/", " ").upper()))
    result = dict(updated=datetime.date.today().isoformat(), method=method,
                  bibtex=bibtex(method_meta, method_arxiv) if method_meta else "",
                  papers=out, credits=credits)
    with open(os.path.join(STATIC, "references.json"), "w") as handle:
        json.dump(result, handle, indent=1, ensure_ascii=False)
    print("%d papers listed, %d background credits" % (len(out), len(credits)))


if __name__ == "__main__":
    main(sys.argv[1])
