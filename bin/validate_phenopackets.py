#!/usr/bin/env python3
"""Validate phenopackets: schema parse, required metadata, resource coverage, HPO term checks.

Base checks (always):
  schema    the JSON parses as a Phenopacket v2 message with no unknown fields
  required  id, subject.id, metaData.created, createdBy, phenopacketSchemaVersion, resources
  resources every CURIE prefix used in an ontology class has a metaData.resources entry
HPO checks (with --vocab, using hp_terms.tsv):
  hp-exists feature and onset terms exist in the release
  hp-obsolete  no obsolete terms
  hp-label  the label written matches the release label (warning)
  hp-onset  onset classes are descendants of Onset
Graph checks (with --hp-json, through OAK; slow to load, ~40 s):
  hp-redundant  a present feature that is an ancestor of another present feature (warning)
  hp-conflict   an excluded feature that is an ancestor of a present feature (error)
Writes a TSV report; exits non-zero with --strict when any error is found.
"""
import argparse, csv, json, re, sys
from pathlib import Path
import phenopackets as pp
from google.protobuf.json_format import ParseDict, ParseError

CURIE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*:\S+$")


def walk_classes(obj, path="$"):
    if isinstance(obj, dict):
        if set(obj) >= {"id", "label"} and isinstance(obj["id"], str) and CURIE.match(obj["id"]):
            yield path, obj
        for k, v in obj.items():
            yield from walk_classes(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_classes(v, f"{path}[{i}]")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phenopackets", type=Path, required=True)
    ap.add_argument("--vocab", type=Path)
    ap.add_argument("--hp-json", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    hp = {}
    if a.vocab and (a.vocab / "hp_terms.tsv").exists():
        with open(a.vocab / "hp_terms.tsv", newline="") as f:
            hp = {r["id"]: r for r in csv.DictReader(f, delimiter="\t")}
    adapter = None
    if a.hp_json:
        from oaklib import get_adapter
        adapter = get_adapter(f"obograph:{a.hp_json}")
    rows = []

    def add(file, level, check, msg):
        rows.append({"file": file, "level": level, "check": check, "message": msg})

    files = sorted(a.phenopackets.glob("*.phenopacket.json"))
    for fp in files:
        name = fp.name
        d = json.loads(fp.read_text())
        try:
            ParseDict(d, pp.Phenopacket())
        except ParseError as e:
            add(name, "error", "schema", str(e)); continue
        md = d.get("metaData", {})
        for key, val in (("id", d.get("id")), ("subject.id", d.get("subject", {}).get("id")), ("metaData.created", md.get("created")),
                         ("metaData.createdBy", md.get("createdBy")), ("metaData.phenopacketSchemaVersion", md.get("phenopacketSchemaVersion"))):
            if not val: add(name, "error", "required", f"{key} is missing")
        prefixes = {r.get("namespacePrefix") for r in md.get("resources", [])}
        if not prefixes: add(name, "error", "required", "metaData.resources is empty")
        for path, oc in walk_classes(d):
            pre = oc["id"].split(":")[0]
            if pre not in prefixes:
                add(name, "error", "resources", f"{path}: prefix {pre} has no metaData.resources entry")
            if hp and pre == "HP":
                t = hp.get(oc["id"])
                if not t: add(name, "error", "hp-exists", f"{path}: {oc['id']} not in HPO release"); continue
                if t["obsolete"] == "true": add(name, "error", "hp-obsolete", f"{path}: {oc['id']} is obsolete" + (f", replaced by {t['replaced_by']}" if t["replaced_by"] else ""))
                if oc.get("label") != t["label"]: add(name, "warning", "hp-label", f"{path}: label {oc.get('label')!r} differs from release {t['label']!r}")
                if path.endswith(".onset.ontologyClass") and t["kind"] != "onset":
                    add(name, "error", "hp-onset", f"{path}: {oc['id']} is not an Onset class")
        if adapter:
            from oaklib.datamodels.vocabulary import IS_A
            feats = d.get("phenotypicFeatures", [])
            present = {f["type"]["id"] for f in feats if not f.get("excluded")}
            excluded = {f["type"]["id"] for f in feats if f.get("excluded")}
            for t in present:
                anc = set(adapter.ancestors([t], predicates=[IS_A])) - {t}
                for r in anc & present: add(name, "warning", "hp-redundant", f"{r} is an ancestor of present feature {t}")
                for r in anc & excluded: add(name, "error", "hp-conflict", f"excluded {r} is an ancestor of present feature {t}")
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "level", "check", "message"], delimiter="\t", lineterminator="\n"); w.writeheader(); w.writerows(rows)
    errors = sum(1 for r in rows if r["level"] == "error"); warnings = len(rows) - errors
    print(f"validated {len(files)} phenopackets: {errors} errors, {warnings} warnings -> {a.out}")
    if a.strict and errors: sys.exit(1)


if __name__ == "__main__":
    main()
