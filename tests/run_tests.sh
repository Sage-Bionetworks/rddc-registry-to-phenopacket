#!/usr/bin/env bash
# Run the stages directly (no Nextflow) on the synthetic fixtures and require a clean round trip.
set -euo pipefail
cd "$(dirname "$0")/.."
PATH="$PWD/.venv/bin:$PATH"
OUT=results/pytest
rm -rf "$OUT"; mkdir -p "$OUT"
T=schema/registry_record.yaml

linkml-map map-data -T mappings/nordlike_to_record.transform.yaml -s schema/sources/nordlike_export.yaml \
  --target-schema $T --source-type Export --strict -f json -o "$OUT/nordlike.records.json" tests/data/nordlike/export.json 2> "$OUT/nordlike.map.log"
linkml-map map-data -T mappings/redcaplike_to_record.transform.yaml -s schema/sources/redcaplike_wide.yaml \
  --target-schema $T --source-type Row --strict -f jsonl -o "$OUT/redcaplike.records.jsonl" tests/data/redcaplike/Row.csv 2> "$OUT/redcaplike.map.log"

for R in nordlike redcaplike; do
  F="$OUT/$R.records.json"; [ -f "$F" ] || F="$OUT/$R.records.jsonl"
  bin/crosswalk.py --records "$F" --assets assets --registry "$R" --out "$OUT/$R.resolved.jsonl" --unmapped "$OUT/$R.unmapped.tsv"
  bin/build_phenopackets.py --resolved "$OUT/$R.resolved.jsonl" --assets assets --outdir "$OUT/$R"
  bin/roundtrip_check.py --truth tests/data/truth.jsonl --registry "$R" --phenopackets "$OUT/$R/phenopackets" \
    --unmapped "$OUT/$R.unmapped.tsv" --out "$OUT/$R.roundtrip.tsv" --strict
  # The batch sidecar's subjects (idSystem contributor) must match the participants one to one.
  python3 -c "import json,sys; print('\n'.join(s['subjectId'] for s in json.load(open(sys.argv[1]))['subjects']))" \
    "tests/data/$R/_sidecar.json" > "$OUT/$R.sidecar_subjects.txt"
  bin/reconcile_subjects.py --records "$OUT/$R.resolved.jsonl" --subjects "$OUT/$R.sidecar_subjects.txt" \
    --out "$OUT/$R.subjects.tsv" --strict > /dev/null
done

# A subject list that drops one participant and adds an unknown one must fail.
{ tail -n +2 "$OUT/nordlike.sidecar_subjects.txt"; echo "NL-9999"; } > "$OUT/bad_subjects.txt"
if bin/reconcile_subjects.py --records "$OUT/nordlike.resolved.jsonl" --subjects "$OUT/bad_subjects.txt" \
     --out "$OUT/bad.subjects.tsv" --strict > /dev/null 2>&1; then
  echo "FAIL: mismatched subjects were not detected"; exit 1
fi
grep -q $'^records_not_in_sidecar\t1\tfail$' "$OUT/bad.subjects.tsv"
grep -q $'^sidecar_subjects_without_record\t1\tfail$' "$OUT/bad.subjects.tsv"
echo "OK: both registries round-trip and reconcile with their sidecars; outputs in $OUT"
