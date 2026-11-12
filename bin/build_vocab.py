#!/usr/bin/env python3
"""Build the vocabulary tables the crosswalk and validator read, from ontology releases, with OAK.

Inputs
  --hp-json      hp.json (OBO Graphs) from http://purl.obolibrary.org/obo/hp.json, read through
                 the Ontology Access Kit obograph adapter
  --mondo-sssom  mondo.sssom.tsv, Mondo's published cross-references (Orphanet, OMIM, ICD10CM, ...)
  --hgnc         hgnc_complete_set.txt from genenames.org

Outputs (TSV, in --out)
  hp_terms.tsv       id, label, obsolete, replaced_by, kind (onset | feature)
  hp_synonyms.tsv    synonym, hpo_id, scope (exact | related | broad | narrow)
  mondo_xrefs.tsv    xref, mondo_id, mondo_label, predicate
  mondo_labels.tsv   mondo_id, label
  genes.tsv          symbol, hgnc_id, name, kind (symbol | alias | prev)
  versions.yml       release identifiers, written into each phenopacket's metaData.resources

--subset-from FILE...  keep only the HP ids, MONDO ids and gene symbols found in the given
                       TSVs (columns id, hpo_id, mondo_id, gene_symbol), plus replacements and
                       the onset classes. Used to re-derive the committed assets/ subset so it
                       is a true slice of a release.
"""
import argparse, csv, datetime, json, re
from pathlib import Path
import yaml

ONSET_ROOT = "HP:0003674"
REPLACED_BY = "http://purl.obolibrary.org/obo/IAO_0100001"
SCOPES = {"hasExactSynonym": "exact", "hasRelatedSynonym": "related", "hasBroadSynonym": "broad", "hasNarrowSynonym": "narrow"}
HP_IRI = "http://purl.obolibrary.org/obo/HP_"


def write_tsv(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n"); w.writerow(header); w.writerows(rows)


def load_subset(files):
    hp, mondo, genes = set(), set(), set()
    for fp in files:
        with open(fp, newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                for k in ("id", "hpo_id"):
                    if r.get(k, "").startswith("HP:"): hp.add(r[k])
                if r.get("mondo_id"): mondo.add(r["mondo_id"])
                if r.get("gene_symbol"): genes.add(r["gene_symbol"].upper())
    return hp, mondo, genes


def build_hp(hp_json, out, subset):
    from oaklib import get_adapter
    from oaklib.datamodels.vocabulary import IS_A
    adapter = get_adapter(f"obograph:{hp_json}")
    graph = json.load(open(hp_json))["graphs"][0]
    version = graph.get("meta", {}).get("version", "")
    m = re.search(r"/releases/(\d{4}-\d{2}-\d{2})/", version)
    hp_version = m.group(1) if m else version
    # Labels, synonyms, obsoletion and replacement are read from the raw graph: per-entity
    # OAK calls on the obograph adapter take minutes for 20k terms, and its obsoletes()
    # fails on nodes without a meta block (oaklib 0.7.4). OAK supplies the Onset subtree.
    onset = set(adapter.descendants([ONSET_ROOT], predicates=[IS_A], reflexive=True))
    nodes = {}
    for n in graph["nodes"]:
        if not n["id"].startswith(HP_IRI): continue
        nodes["HP:" + n["id"][len(HP_IRI):]] = n
    replaced = {c: b["val"] for c, n in nodes.items() for b in (n.get("meta") or {}).get("basicPropertyValues", []) if b.get("pred") == REPLACED_BY}
    keep = None
    if subset:
        keep = set(subset) | onset
        keep |= {replaced[h] for h in subset if h in replaced}
    terms, syns = [], []
    for e, n in nodes.items():
        if keep is not None and e not in keep: continue
        meta = n.get("meta") or {}
        label = n.get("lbl", "")
        obsolete = bool(meta.get("deprecated"))
        terms.append((e, label, "true" if obsolete else "false", replaced.get(e, ""), "onset" if e in onset else "feature"))
        if obsolete: continue
        for syn in meta.get("synonyms", []):
            scope = SCOPES.get(syn.get("pred", ""))
            if scope and syn.get("val") and syn["val"] != label:
                syns.append((syn["val"], e, scope))
    terms.sort(); syns.sort()
    write_tsv(out / "hp_terms.tsv", ["id", "label", "obsolete", "replaced_by", "kind"], terms)
    write_tsv(out / "hp_synonyms.tsv", ["synonym", "hpo_id", "scope"], syns)
    print(f"HPO {hp_version}: {len(terms)} terms, {len(syns)} synonyms")
    return hp_version


def build_mondo(sssom, out, subset):
    version, rows, labels = "", [], {}
    with open(sssom, newline="") as f:
        header_lines = []
        pos = 0
        for line in f:
            if line.startswith("#"): header_lines.append(line[1:].strip()); pos += len(line)
            else: break
        meta = yaml.safe_load("\n".join(header_lines)) or {}
        version = str(meta.get("mapping_set_version") or meta.get("mapping_date") or "")
        f.seek(pos)
        for r in csv.DictReader(f, delimiter="\t"):
            s, o = r["subject_id"], r["object_id"]
            if not s.startswith("MONDO:"): continue
            if subset is not None and s not in subset: continue
            labels[s] = r.get("subject_label", "")
            if o.split(":")[0] in ("Orphanet", "OMIM", "OMIMPS", "ICD10CM", "ICD10WHO", "DOID", "MESH", "UMLS", "NCIT", "SCTID"):
                rows.append((o, s, r.get("subject_label", ""), r.get("predicate_id", "")))
    rows.sort()
    if not version:  # the published SSSOM header carries no version; record the download date
        version = "download-" + datetime.date.fromtimestamp(Path(sssom).stat().st_mtime).isoformat()
    write_tsv(out / "mondo_xrefs.tsv", ["xref", "mondo_id", "mondo_label", "predicate"], rows)
    write_tsv(out / "mondo_labels.tsv", ["mondo_id", "label"], sorted(labels.items()))
    print(f"MONDO {version or 'unversioned'}: {len(labels)} diseases, {len(rows)} cross-references")
    return version


def build_hgnc(hgnc, out, subset):
    rows = []
    with open(hgnc, newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if r.get("status") != "Approved": continue
            sym = r["symbol"]
            if subset is not None and sym.upper() not in subset: continue
            rows.append((sym, r["hgnc_id"], r["name"], "symbol"))
            for k, kind in (("alias_symbol", "alias"), ("prev_symbol", "prev")):
                for a in filter(None, (x.strip() for x in (r.get(k) or "").split("|"))):
                    rows.append((a, r["hgnc_id"], r["name"], kind))
    rows.sort()
    write_tsv(out / "genes.tsv", ["symbol", "hgnc_id", "name", "kind"], rows)
    mtime = datetime.date.fromtimestamp(Path(hgnc).stat().st_mtime).isoformat()
    print(f"HGNC (downloaded {mtime}): {len(rows)} symbol rows")
    return mtime


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hp-json", type=Path, required=True)
    ap.add_argument("--mondo-sssom", type=Path, required=True)
    ap.add_argument("--hgnc", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--subset-from", type=Path, nargs="*")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    hp_sub = mondo_sub = gene_sub = None
    if a.subset_from:
        hp_sub, mondo_sub, gene_sub = load_subset(a.subset_from)
    versions = {
        "HP": build_hp(a.hp_json, a.out, hp_sub),
        "MONDO": build_mondo(a.mondo_sssom, a.out, mondo_sub),
        "HGNC": "download-" + build_hgnc(a.hgnc, a.out, gene_sub),
        "RxNorm": "lexicon-only",
        "built_on": datetime.date.today().isoformat(),
        "subset": bool(a.subset_from),
    }
    (a.out / "versions.yml").write_text(yaml.safe_dump(versions, sort_keys=False))
    print(f"wrote tables and versions.yml to {a.out}")


if __name__ == "__main__":
    main()
