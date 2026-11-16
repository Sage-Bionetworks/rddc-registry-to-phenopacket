#!/usr/bin/env python3
"""Reconcile the participants of a registry export with the subjects its batch sidecar lists.

The sidecar's subjects (idSystem `contributor`) are the registry's participant IDs, so they
must match the records one to one. Writes a TSV of counts (no identifiers):
  check                          value  status
  sidecar_subjects               N      ok
  records                        N      ok
  sidecar_subjects_without_record n     ok|fail
  records_not_in_sidecar         n     ok|fail
  duplicate_record_ids           n     ok|fail
--strict exits 1 if any check fails.
"""

import argparse
import csv
import json
import sys
from collections import Counter


def record_ids(path):
    with open(path) as f:
        text = f.read()
    if path.endswith(".jsonl"):
        return [json.loads(line)["id"] for line in text.splitlines() if line.strip()]
    doc = json.loads(text)
    recs = doc if isinstance(doc, list) else next(v for v in doc.values() if isinstance(v, list))
    return [r["id"] for r in recs]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--records", required=True, help="resolved records (JSON Lines, from crosswalk.py)")
    ap.add_argument("--subjects", required=True, help="the sidecar's subject IDs, one per line")
    ap.add_argument("--out", required=True)
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()

    ids = record_ids(a.records)
    with open(a.subjects) as f:
        subjects = {line.strip() for line in f if line.strip()}
    have = set(ids)
    dupes = sum(n - 1 for n in Counter(ids).values() if n > 1)
    rows = [
        ("sidecar_subjects", len(subjects), "ok"),
        ("records", len(ids), "ok"),
        ("sidecar_subjects_without_record", len(subjects - have), "ok" if subjects <= have else "fail"),
        ("records_not_in_sidecar", len(have - subjects), "ok" if have <= subjects else "fail"),
        ("duplicate_record_ids", dupes, "ok" if dupes == 0 else "fail"),
    ]
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["check", "value", "status"])
        w.writerows(rows)
    failed = [r[0] for r in rows if r[2] == "fail"]
    for r in rows:
        print("\t".join(map(str, r)))
    if failed and a.strict:
        sys.exit(f"subjects do not reconcile: {', '.join(failed)}")


if __name__ == "__main__":
    main()
