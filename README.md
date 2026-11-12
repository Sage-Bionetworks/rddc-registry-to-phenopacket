# rddc-registry-to-phenopacket

Prototype: patient-registry exports in two shapes, a hierarchical JSON export and a wide
one-row-per-participant table with a data dictionary, mapped with
[LinkML-Map](https://linkml.io/linkml-map/) into one intermediate LinkML schema and then
built into GA4GH Phenopackets v2. The point is to find out what one target can absorb from
two mapping styles, and to make visible what it cannot.

Status: scaffold, runs end to end on synthetic fixtures. See [What is and is not verified](#what-is-and-is-not-verified).

## Layout

```
schema/registry_record.yaml       intermediate schema (target of every mapping); prototype-local, not in rddc-model
schema/sources/                   one LinkML schema per registry export shape
  nordlike_export.yaml              hierarchical JSON, hand-written from the inferred export shape
  redcaplike_wide.yaml              wide table, GENERATED from the data dictionary by bin/gen_wide_spec.py
mappings/                         LinkML-Map specifications, one per registry
  nordlike_to_record.transform.yaml   hand-curated, class for class
  redcaplike_to_record.transform.yaml GENERATED from the dictionary's curated rddc_target column
assets/                           vendored, verified vocabulary subsets so tests run offline (see assets/README.md)
bin/                              the stages (also on PATH inside Nextflow processes)
  gen_registry_data.py              synthetic fixtures for both registries + ground truth
  gen_wide_spec.py                  data dictionary -> source schema + mapping spec
  crosswalk.py                      codes and texts -> HPO / MONDO / HGNC / RxNorm, with an unmapped report
  build_phenopackets.py             resolved records -> phenopacket + extras per participant
  roundtrip_check.py                phenopackets vs ground truth
main.nf, modules/local/           Nextflow pipeline: LINKML_MAP -> CROSSWALK -> BUILD_PHENOPACKETS -> [VALIDATE] -> ROUNDTRIP_CHECK
tests/                            samplesheet, fixtures (tests/data), tests/run_tests.sh (stages without Nextflow)
```

## Quick start

```bash
make tools      # uv virtualenv (.venv), nextflow and phenopacket-tools into .tools/
make test       # stages on the fixtures, strict round trip, no Nextflow   (~20 s)
make nf-test    # full pipeline, -profile test,local, results in results/test
make validate   # phenopacket-tools validation of results/test (Java)
make lint       # schema lint and both mapping specs validated against source and target
make data spec  # regenerate fixtures, recompile the wide-table schema and spec
```

Outputs per registry in `results/test/<registry>/`:

| File | What |
| --- | --- |
| `<registry>.records.json` or `.jsonl` | LinkML-Map output: RegistryRecord objects |
| `<registry>.resolved.jsonl` | the same records with resolution fields (hpo_id, mondo_id, hgnc_id, rxcui, onset_hpo, resolution) |
| `<registry>.unmapped.tsv` | every value that did not resolve, with the field and the reason |
| `phenopackets/<id>.phenopacket.json` | one phenopacket per participant |
| `extras/<id>.extras.json` | everything the phenopacket could not hold, verbatim, plus an `unrepresented` list saying why |
| `build_report.tsv` | per-participant counts: features, diseases, interpretations, actions, files, unknowns, unresolved, unrepresented |
| `<registry>.roundtrip.tsv` | pass or FAIL per participant against the generator's truth (fixtures only) |

`results/test/summary/` concatenates the unmapped, build and round-trip reports across registries.

## How the two shapes map

Both registries land in the same nested `RegistryRecord`: participant, diseases, surveys
with their answers and scores, medications, family history, documents. Nothing is
flattened before terms are resolved, because the survey and its version are what the
crosswalk needs to look codes up.

**Hierarchical JSON** maps class for class. `Participant` to `RegistryRecord`, `Survey` to
`SurveyResponse`, `Item` to `Answer`, and so on, each as its own class derivation. Nested
single objects are reached with dot paths (`demographics.sex`). An item with a code is a
checklist answer; one without is free text, decided by a `case(...)` expression.

**Wide table** maps one row to one record. Each symptom column becomes one `Answer` through
a list of nested `class_derivations`, grouped under one `SurveyResponse` per form. Coded
answers decode through `value_mappings` from the dictionary's choices; the compiler looks
the target slot's enum up in `registry_record.yaml` and writes permissible-value keys, so
the spec validates with `--strict`. The dictionary carries one curated column,
`rddc_target`, that says where each field lands (`record.sex`, `answer`,
`answer_onset:<field>`, `med[2].name_text`, `score:total`, ...). That column is the
mapping curation; everything else is compiled.

Things LinkML-Map 0.6 decided for this design, found while building it:

- Building records inside an expression (a list comprehension over `surveys[].items[]`)
  is refused by design; the tool wants a class derivation per nested class. That is why the
  intermediate keeps the nesting and the flattening happens in `build_phenopackets.py`.
- A list of `class_derivations` on a slot, each `populated_from: Row`, is the supported way
  to turn N columns into N objects. It is verbose, hence the compiler.
- Enum values resolve by key, meaning, title, then aliases. YAML reads bare `yes` and `no`
  as booleans, so those aliases must be quoted. A permissible value named `self` breaks
  the LinkML loader.
- `missing_values: [""]` on each wide-table slot keeps empty cells from becoming empty
  strings that then fail enum resolution under `--strict`.

## Resolution and what is reported

`crosswalk.py` resolves in a fixed order and never guesses silently. A checklist answer
uses the inline code if the registry supplies one (checked against the HPO table, obsolete
codes replaced only when a replacement is known), else the survey lookup
`assets/survey_lookups/<registry>_<instrument>_<version>.tsv`, else an exact label match.
Free text is split on `;`, `,` and `and`, and each phrase is matched against a small
lay-term lexicon. Disease codes go through MONDO cross-references (`ORPHA:` and `OMIM:`),
then label. Medications match a drug lexicon with brand names. Everything else lands in
`unmapped.tsv` with a reason, and the round-trip check requires the planted unmappable
values to be there.

The fixtures plant: an obsolete inline HPO code (HP:0040083) on every ninth participant,
free-text phrases with and without a lexicon entry, two medications outside the lexicon,
one disease (Dravet) with no ORPHA or OMIM code so that label matching is exercised, and
a wide-table registry that carries no codes at all so that survey lookups are exercised.

## What the prototype surfaced

These are the registry facts that have no home in a phenopacket, as recorded in each
participant's `extras.json` under `unrepresented`. They are the evidence for what the
data model and the normalisation design still need to decide.

- **Respondent attribution.** Who answered (parent, self, caregiver) has no field. The
  phenopacket route is `Evidence` with an ECO term on each feature; not done here.
- **Family history.** A `Family` message needs a pedigree with individual ids; registry
  exports give "mother has mild learning difficulties". Kept verbatim in extras.
- **Instrument scores.** A PedsQL total becomes a `Measurement` only with a coded assay.
  No LOINC code was asserted rather than invent one.
- **Treatment response text.** `MedicalAction.response_to_treatment` needs an ontology
  class; "fewer seizures" is kept as text.
- **Reported versus confirmed diagnosis.** `Disease` has no verification status. Genetic
  confirmation with a gene becomes an `Interpretation` with status SOLVED; a confirmed
  diagnosis without a resolvable gene is listed as unrepresented.
- **Onset bands.** Registry bands do not align with HPO onset classes; `assets/onset_bands.tsv`
  records each assumption in its note column ("over 5 years" to juvenile onset, for one).
- **Birth year and country** are kept in extras, not the phenopacket, to leave the
  de-identification decision outside this step.
- **Unknown answers** ("unsure") are neither present nor excluded and are listed, not dropped.

## What is and is not verified

Verified here: `make test` and `make nf-test` pass with every participant round-tripping
in both registries; both mapping specs pass `linkml-map validate-spec --strict`; every
identifier in `assets/` was checked against OLS, HGNC and RxNav on 2026-11-11.

Not verified: the phenopacket-tools validator (`make validate`, and the optional
`VALIDATE_PHENOPACKETS` process behind `--pxf_jar`) was downloaded but could not be run in
the environment this was scaffolded in, so its command line is unexercised. The Dockerfile
is written but the image has not been built. The vocabulary tables are subsets; a real run
needs full releases through OAK, which is the first follow-up.

## Adding a registry

1. Put a LinkML schema of the export in `schema/sources/`. For a wide table, write the
   dictionary with an `rddc_target` column and run `bin/gen_wide_spec.py`.
2. Write (or generate) the mapping in `mappings/`. Validate it:
   `linkml-map validate-spec --strict --source-schema ... --target-schema schema/registry_record.yaml ...`
3. If checklist items carry no codes, add `assets/survey_lookups/<registry>_<instrument>_<version>.tsv`.
4. Add a samplesheet row: `registry,format,data,source_schema,transform,source_type,truth`.

## Next steps, in order

1. Replace the vendored subsets with OAK-backed HPO, MONDO and HGNC releases and record
   the release in each phenopacket's `metaData.resources`.
2. Run and wire the validator; add `--hpo` validation once a full HPO is available.
3. Decide the four representation gaps above with the model owners, then add the
   phenopacket-to-OMOP projection as a DuckDB module, reusing rddc-fhir-to-omop.
4. Obtain one blank data dictionary and one test export from each real registry on the
   TA1 sheet and replace the inferred source schemas.
