#!/usr/bin/env python3
"""Compare built phenopackets with the generator's ground truth.

For each truth row: present and excluded HPO sets, MONDO, HGNC and RxNorm identifiers
must match exactly; phrases and medications the truth marks as unmappable must appear
in the unmapped report; a planted obsolete code must not appear as a feature.
Exit status is non-zero with --strict when any record fails.
"""
import argparse, csv, json, sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--truth", type=Path, required=True)
    ap.add_argument("--registry", required=True)
    ap.add_argument("--phenopackets", type=Path, required=True)
    ap.add_argument("--unmapped", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    with open(a.unmapped, newline="") as f:
        unm = list(csv.DictReader(f, delimiter="\t"))
    unmapped_by_rec = {}
    for u in unm: unmapped_by_rec.setdefault(u["record_id"], []).append(u["value"])
    rows, failures = [], 0
    for line in a.truth.read_text().splitlines():
        t = json.loads(line)
        if t["registry"] != a.registry: continue
        p = json.loads((a.phenopackets / f"{t['id']}.phenopacket.json").read_text())
        present = {f["type"]["id"] for f in p.get("phenotypicFeatures", []) if not f.get("excluded")}
        excluded = {f["type"]["id"] for f in p.get("phenotypicFeatures", []) if f.get("excluded")}
        mondo = {d["term"]["id"] for d in p.get("diseases", [])}
        hgnc = set()
        for i in p.get("interpretations", []):
            for g in i.get("diagnosis", {}).get("genomicInterpretations", []):
                gd = g.get("gene") or g.get("variantInterpretation", {}).get("variationDescriptor", {}).get("geneContext", {})
                if gd.get("valueId"): hgnc.add(gd["valueId"])
        rx = {m["treatment"]["agent"]["id"].split(":")[1] for m in p.get("medicalActions", []) if "treatment" in m}
        probs = []
        if present != set(t["present"]): probs.append(f"present {sorted(present ^ set(t['present']))}")
        if excluded != set(t["absent"]): probs.append(f"excluded {sorted(excluded ^ set(t['absent']))}")
        if mondo != {t["mondo"]}: probs.append(f"mondo {sorted(mondo)} != {t['mondo']}")
        if hgnc != ({t["hgnc"]} if t.get("hgnc") else set()): probs.append(f"hgnc {sorted(hgnc)} != {t.get('hgnc')}")
        if rx != set(t["rxcui"]): probs.append(f"rxcui {sorted(rx ^ set(t['rxcui']))}")
        um = unmapped_by_rec.get(t["id"], [])
        for phrase in t["unmapped_free_text"] + t["unmapped_medications"]:
            if phrase not in um: probs.append(f"expected in unmapped report: {phrase!r}")
        if t.get("planted_obsolete") and t["planted_obsolete"] in present | excluded:
            probs.append("obsolete code leaked into features")
        ok = not probs
        failures += not ok
        rows.append({"registry": a.registry, "id": t["id"], "status": "pass" if ok else "FAIL", "problems": "; ".join(probs)})
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["registry", "id", "status", "problems"], delimiter="\t", lineterminator="\n"); w.writeheader(); w.writerows(rows)
    print(f"{a.registry}: {len(rows) - failures}/{len(rows)} records round-trip")
    for r in rows:
        if r["status"] == "FAIL": print(f"  {r['id']}: {r['problems']}")
    if a.strict and failures: sys.exit(1)


if __name__ == "__main__":
    main()
