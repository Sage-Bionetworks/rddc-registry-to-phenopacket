# rddc-registry-to-phenopacket

Prototype: patient-registry exports in two shapes, a hierarchical JSON export and a wide
one-row-per-participant table with a data dictionary, mapped with
[LinkML-Map](https://linkml.io/linkml-map/) into one intermediate LinkML schema and then
built into GA4GH Phenopackets v2. The point is to find out what one target can absorb from
two mapping styles, and to make visible what it cannot.

The input is a deposited batch described by its Croissant sidecar (`_sidecar.json`,
[rddc-model](https://github.com/Sage-Bionetworks/rddc-model)), as for the other RDDC
pipelines; see [Input](#input-the-batch-sidecar).

Status: scaffold, runs end to end on synthetic fixtures. See [What is and is not verified](#what-is-and-is-not-verified).

## Layout

```
schema/registry_record.yaml       intermediate schema (target of every mapping); prototype-local, not in rddc-model
schema/sources/                   one LinkML schema per registry export shape
  nordlike_export.yaml              hierarchical JSON, hand-written from the inferred export shape
  redcaplike_wide.yaml              wide table, GENERATED from the data dictionary by bin/gen_wide_spec.py
mappings/sources.yaml             registered sources: per sidecar sourceId, which file is the export and how it maps
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
  reconcile_subjects.py             the export's participants vs the sidecar's subjects
main.nf, modules/local/           Nextflow pipeline: SIDECAR_INTAKE -> LINKML_MAP -> CROSSWALK -> RECONCILE_SUBJECTS,
                                  BUILD_PHENOPACKETS -> [VALIDATE] -> ROUNDTRIP_CHECK
subworkflows/local/sidecar_intake vendored from rddc-genomics-workflows (shared sidecar intake)
tests/                            fixtures: one batch per registry with its _sidecar.json (tests/data/<registry>),
                                  truth, make_sidecars.py, run_tests.sh (stages without Nextflow)
```

## Quick start

```bash
make tools      # uv virtualenv (.venv), nextflow and phenopacket-tools into .tools/
make test       # stages on the fixtures, strict round trip, no Nextflow   (~20 s)
make nf-test    # full pipeline on each test batch (committed vocabulary subset), results in results/test/<registry>
make nf-test-errors # a wrong checksum on the export stops the run after writing intake.tsv
make sidecars   # rewrite the test batches' sidecars, validated against ../rddc-model
make vocab      # download HPO, Mondo SSSOM and HGNC releases, build vocab/tables with OAK (~5 s after download)
make nf-full    # pipeline on the full releases with OAK graph checks in validation (~45 s)
make validate   # phenopacket-tools (Java) validation of results/test/*; see verification notes
make lint       # schema lint and both mapping specs validated against source and target
make data spec  # regenerate fixtures, recompile the wide-table schema and spec
make assets-subset  # re-derive the committed assets/ vocabulary subset as a slice of the release
```

One run per batch:

```bash
.tools/nextflow run . -profile local --sidecar /path/to/batch/_sidecar.json --outdir results/<batch>
```

## Input: the batch sidecar

- **Files.** `SIDECAR_INTAKE` (vendored from rddc-genomics-workflows, shared with the other
  pipelines) resolves each `contentUrl` against the sidecar's location, stages the file and
  checks md5 (and sha256). `intake/intake.tsv` lists every entry with its route: `map` (the
  export), `documentation` (its data dictionary), `skipped`, `rejected` (with the reason).
- **Which mapping.** The sidecar's `sourceId` selects the source's registered mapping in
  `mappings/sources.yaml` (`--sources`): the export's class and `encodingFormat`, its source
  schema, LinkML-Map transform and source type, and the registry name. Mappings belong to a
  source, set up once at onboarding, so they are not in the sidecar. The batch must have
  exactly one usable file matching the export; otherwise the run stops after writing
  `intake.tsv` (`CHECK_EXPORT`), e.g. when the export failed its checksum.
- **Subjects.** The sidecar's subjects (idSystem `contributor`) are the registry's
  participant IDs. `RECONCILE_SUBJECTS` checks them one to one against the records
  (`<registry>.subjects.tsv`); a mismatch fails the run under `--strict_validation` (default).
- **Test fixtures.** `tests/data/nordlike/` (a `TabularFile`, JSON) and
  `tests/data/redcaplike/` (an `IntakeFormFile` whose `formDefinition` is its data
  dictionary, a `DocumentationFile`) are one batch each. `tests/make_sidecars.py` writes their
  sidecars (`make sidecars`), validated against rddc-model's JSON Schema: rddc-sidecar 0.1.0
  vendors an older model without `IntakeFormFile`. `--truth` is the generator's ground truth
  for the round-trip check; it is not part of a deposit.

Outputs per batch in `<outdir>/`, and per registry in `<outdir>/<registry>/`:

| File | What |
| --- | --- |
| `<registry>.records.json` or `.jsonl` | LinkML-Map output: RegistryRecord objects |
| `<registry>.resolved.jsonl` | the same records with resolution fields (hpo_id, mondo_id, hgnc_id, rxcui, onset_hpo, resolution) |
| `<registry>.unmapped.tsv` | every value that did not resolve, with the field and the reason |
| `phenopackets/<id>.phenopacket.json` | one phenopacket per participant |
| `extras/<id>.extras.json` | everything the phenopacket could not hold, verbatim, plus an `unrepresented` list saying why |
| `build_report.tsv` | per-participant counts: features, diseases, interpretations, actions, files, unknowns, unresolved, unrepresented |
| `<registry>.validation.tsv` | validator findings: schema, required metadata, resource coverage, HPO existence, obsoletion, label drift, onset class, and with `--hp_json` ancestor redundancy and conflicts |
| `<registry>.roundtrip.tsv` | pass or FAIL per participant against the generator's truth (fixtures only) |
| `<registry>.subjects.tsv` | the sidecar's subjects vs the records: counts and ok/fail |
| `intake/intake.tsv`, `intake/batch.json` | (in `<outdir>/`) every sidecar entry with its route and reason; the batch header |

`<outdir>/summary/` holds the unmapped, build, validation and round-trip reports of the run.

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
uses the inline code if the registry supplies one (checked against the HPO release,
obsolete codes replaced only when the release names a live replacement), else the survey
lookup `assets/survey_lookups/<registry>_<instrument>_<version>.tsv`, else an exact match
on a release label, else on an exact or related release synonym. Free text is split on
`;`, `,` and `and`, and each phrase goes through the lay-term lexicon, then release labels
and synonyms, then a lexicon key contained in the phrase.

Vocabulary comes in two layers. `--vocab` points at release tables built by
`bin/build_vocab.py` (`make vocab`): HPO from hp.json through OAK, Mondo cross-references
from its published SSSOM file, gene symbols from the HGNC complete set, plus a
`versions.yml` that is written into every phenopacket's `metaData.resources`. `--assets`
holds the curated tables (onset bands, lay terms, drug lexicon, survey lookups) and a
committed subset of the release tables, derived by `make assets-subset`, so the test
profile runs offline against a true slice of the 2026-09-01 HPO release. The generator
derives its truth through the pipeline's own resolver, so the truth follows the release:
when the release names a live replacement for a planted obsolete code, the replacement is
expected, and a phrase that matches a release synonym is expected to resolve. Disease codes go through MONDO cross-references (`ORPHA:` and `OMIM:`),
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

Verified here: `make test`, `make nf-test` and `make nf-full` pass with every participant
round-tripping in both registries, against the committed subset and against the full
HPO 2026-09-01, Mondo and HGNC releases. The Python validator in the pipeline reports no
errors or warnings on either run, including OAK ancestor checks in `nf-full`. Both mapping
specs pass `linkml-map validate-spec --strict`. The committed `assets/` vocabulary subset is
derived from the releases by `make assets-subset`; the curated tables were checked against
OLS, HGNC and RxNav on 2026-11-11.

Not verified: the phenopacket-tools Java validator (`make validate`, and the optional
`VALIDATE_PXF` process behind `--pxf_jar`) was downloaded but could not be run in the
environment this was built in, so its command line is unexercised; the Python validator
covers the same base checks and the HPO checks. The image
(`ghcr.io/sage-bionetworks/rddc-registry-to-phenopacket`, `make image`) is built and both
test batches pass in it (`make nf-test-docker`). RxNorm has no licence-free bulk download, so medications still resolve
through the curated lexicon only.

## Running in Cirro

`.cirro/` holds the run configuration for [Cirro](https://cirro.bio): the run form
(`process-form.json`), how form values become pipeline parameters (`process-input.json`) and
a pre-run script (`preprocess.py`) that sets `--sidecar` to the `_sidecar.json` at the root of
the input dataset. The input dataset is one deposited batch. The form offers only
`strict_validation`; the vocabulary is the subset in `assets/`, and `--truth`, `--vocab`,
`--hp_json` and `--pxf_jar` are not offered there yet.

## Adding a registry

1. Put a LinkML schema of the export in `schema/sources/`. For a wide table, write the
   dictionary with an `rddc_target` column and run `bin/gen_wide_spec.py`.
2. Write (or generate) the mapping in `mappings/`. Validate it:
   `linkml-map validate-spec --strict --source-schema ... --target-schema schema/registry_record.yaml ...`
3. If checklist items carry no codes, add `assets/survey_lookups/<registry>_<instrument>_<version>.tsv`.
4. Register the source in `mappings/sources.yaml` under its `sourceId`: registry name, the
   export's sidecar class and `encodingFormat`, format, source schema, transform and source type.

## Next steps, in order

1. Decide the representation gaps above with the model owners, then add the
   phenopacket-to-OMOP projection as a DuckDB module, reusing rddc-fhir-to-omop.
2. Obtain one blank data dictionary and one test export from each real registry on the
   TA1 sheet and replace the inferred source schemas.
3. Run the Java validator once in an environment that allows it.
