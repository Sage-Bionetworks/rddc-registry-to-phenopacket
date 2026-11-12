# Changelog

Findings are recorded here as they are made, newest first. Dates are when the work was done.

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
