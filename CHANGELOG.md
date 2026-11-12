# Changelog

Findings are recorded here as they are made, newest first. Dates are when the work was done.

## 0.2.0 (2026-11-12) release-backed vocabulary and validation

`make vocab` builds HPO, Mondo and HGNC tables from releases; a Python validator runs in
the pipeline; `make nf-full` runs the fixtures against the full releases with OAK checks.

Findings:

- **Release synonyms resolve most lay checklist labels.** "Hearing loss", "Low muscle
  tone" and "Developmental delay" are HPO synonyms, so a release-backed label and synonym
  index resolves checklist items that the subset needed curated lookups for.
- **Obsolete codes get live replacements from the release.** HP:0040083 (toe walking) is
  replaced by HP:0030051 tip-toe gait; with the release, "toe walking" free text resolves
  through a synonym too. The generator's truth follows the release through the shared
  resolver, so fixtures stay honest across releases.
- **OAK's obograph adapter is not for per-term loops.** Per-entity label and alias calls
  take minutes for 20k terms and `obsoletes()` crashes on nodes without a meta block
  (oaklib 0.7.4). Read labels, synonyms and deprecation from the raw graph; use OAK for
  the subtree query. The build then takes seconds.
- **Download sources moved.** The bbop-sqlite mirror returned 403 and the GitHub
  latest-release SSSOM URL 404; the OBO purls work. Mondo's SSSOM header carries no
  version, so the download date is recorded instead. RxNorm has no licence-free bulk file.
- **Validation is clean against the release.** No errors or warnings on the synthetic
  fixtures, including ancestor redundancy and conflict checks; 48 of 48 round-trip.
- **Still not verified:** the phenopacket-tools Java validator could not be run here.

## 0.1.0 (2026-11-11) scaffold

Two inferred registry export shapes map into one intermediate LinkML schema with LinkML-Map
0.6, then to GA4GH Phenopackets v2. Synthetic fixtures, both registries round-trip.

Findings:

- **One nested intermediate works for both shapes.** Hierarchical JSON maps class for class;
  a wide table maps through a list of nested class derivations, one per column. No source
  needed an escape into Python before term resolution.
- **LinkML-Map refuses to build records in expressions.** A comprehension over nested lists
  raises a deliberate error. Keep source nesting in the target and flatten later.
- **Wide-table specs are long, so compile them.** The data dictionary plus one curated
  column (`rddc_target`) generates the source schema and the spec. The compiler reads the
  target schema to write permissible-value keys, which makes `--strict` validation clean.
- **YAML and LinkML traps.** Bare `yes`/`no` aliases become booleans; a permissible value
  named `self` breaks the loader; `missing_values: [""]` is needed on every wide-table slot.
- **Registry data only holds what the checklists ask.** Disease-typical features outside a
  survey never appear; the fixtures were corrected to reflect that.
- **Phenopacket gaps, per participant in extras.json:** respondent attribution, family
  history without a pedigree, instrument scores without a coded assay, treatment response
  text, reported-versus-confirmed diagnosis, onset bands that straddle HPO onset classes,
  birth year and country held back for de-identification.
- **Not verified:** phenopacket-tools validator not run; Docker image not built; vocabulary
  tables are verified subsets, not releases.
