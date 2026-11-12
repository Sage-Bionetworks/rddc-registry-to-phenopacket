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
done
echo "OK: both registries round-trip; outputs in $OUT"
