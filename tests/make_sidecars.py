"""Write _sidecar.json for each test registry batch (tests/data/nordlike, tests/data/redcaplike).

Each synthetic registry export is one batch, as a deposit would be. The sidecars follow
rddc-model (branch `sidecar`): the subjects are the export's participants (idSystem
`contributor`); the NORD-like JSON export is a TabularFile; the REDCap-like wide table is an
IntakeFormFile whose formDefinition is its data dictionary (a DocumentationFile).

rddc-sidecar 0.1.0 vendors an older model without IntakeFormFile and formDefinition, and
cannot infer registry subjects, so it cannot write these yet; once it can, generate them with
`rddc-sidecar from-table`. Also writes nordlike/_sidecar.errors.json (one wrong checksum) for
the intake rejection test.

Usage (from the repo root; rerun after `make data`):
    python3 -I tests/make_sidecars.py --context ../rddc-model/examples/ccda_document_set.json \
        --schema ../rddc-model/schema/generated/rddc_sidecar.schema.json
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"


def uuid(batch: int, n: int) -> str:
    return f"urn:uuid:3c9a7e10-{batch:04d}-4000-8000-{n:012d}"


def file_object(batch_dir: Path, n: int, batch: int, key: str, cls: str, fmt: str, subjects, extra=None):
    data = (batch_dir / key).read_bytes()
    obj = {
        "@id": uuid(batch, n),
        "@type": "cr:FileObject",
        "additionalType": f"rddc:{cls}",
        "name": key,
        "contentUrl": key,
        "contentSize": f"{len(data)} B",
        "encodingFormat": fmt,
        "sha256": hashlib.sha256(data).hexdigest(),
        "md5": hashlib.md5(data).hexdigest(),
    }
    if subjects is not None:
        obj["subjectIds"] = subjects
    obj.update(extra or {})
    return obj


def sidecar(context, batch: int, source_id: str, batch_id: str, description: str, subjects, distribution):
    return {
        "@context": context,
        "@id": uuid(batch, 1),
        "@type": "sc:Dataset",
        "conformsTo": ["http://mlcommons.org/croissant/1.1", "https://w3id.org/rddc/sidecar/0.1.0"],
        "name": f"{source_id}/{batch_id}",
        "url": f"s3://rddc-deposit-test/{source_id}/{batch_id}/",
        "dateCreated": "2026-11-16T00:00:00Z",
        "wasAttributedTo": {"@type": "sc:SoftwareApplication", "name": "make_sidecars.py",
                            "softwareVersion": "0.1.0"},
        "contributorId": "test-site",
        "sourceId": source_id,
        "batchId": batch_id,
        "interaction": "add",
        "sensitivity": {
            "directIdentifiersRemoved": True,
            "synthetic": True,
            "containsDates": True,
            "containsZipCodes": False,
            "containsFreeText": True,
            "containsBiometricIdentifiers": False,
        },
        "description": description,
        "subjects": [{"subjectId": s, "idSystem": "contributor"} for s in subjects],
        "distribution": distribution,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", required=True, help="an rddc-model example sidecar; its @context is copied")
    ap.add_argument("--schema", help="rddc-model's generated sidecar JSON Schema; validate against it")
    args = ap.parse_args()
    context = json.load(open(args.context))["@context"]

    nord = DATA / "nordlike"
    nord_ids = [p["participant_id"] for p in json.load(open(nord / "export.json"))["participants"]]
    red = DATA / "redcaplike"
    with open(red / "Row.csv", newline="") as f:
        red_ids = [r["record_id"] for r in csv.DictReader(f)]

    docs = {
        nord: sidecar(context, 1, "src-nordlike-01", "2026-11-export", "Synthetic NORD-like registry export.",
                      nord_ids, [file_object(nord, 11, 1, "export.json", "TabularFile", "application/json", nord_ids)]),
        red: sidecar(context, 2, "src-redcaplike-01", "2026-11-export", "Synthetic REDCap-like registry export.",
                     red_ids, [
                         file_object(red, 11, 2, "Row.csv", "IntakeFormFile", "text/csv", red_ids,
                                     {"formDefinition": {"@id": uuid(2, 12)}}),
                         file_object(red, 12, 2, "dictionary.csv", "DocumentationFile", "text/csv", None),
                     ]),
    }

    validator = None
    if args.schema:
        import jsonschema
        schema = json.load(open(args.schema))
        validator = jsonschema.validators.validator_for(schema)(schema)
    for batch_dir, doc in docs.items():
        if validator:
            errors = list(validator.iter_errors(doc))
            for e in errors:
                print(f"{batch_dir.name}: {'/'.join(map(str, e.absolute_path))}: {e.message[:300]}")
            if errors:
                raise SystemExit(f"{batch_dir.name}: {len(errors)} schema errors")
        (batch_dir / "_sidecar.json").write_text(json.dumps(doc, indent=2) + "\n")
        print(f"wrote {batch_dir / '_sidecar.json'} ({len(doc['subjects'])} subjects)")

    errors_doc = json.loads(json.dumps(docs[nord]))
    errors_doc["@id"] = uuid(1, 2)
    errors_doc["distribution"][0]["md5"] = "0" * 32
    (nord / "_sidecar.errors.json").write_text(json.dumps(errors_doc, indent=2) + "\n")
    print(f"wrote {nord / '_sidecar.errors.json'} (wrong checksum on export.json)")


if __name__ == "__main__":
    main()
