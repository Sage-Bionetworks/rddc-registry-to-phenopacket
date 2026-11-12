# Vendored vocabulary subsets

Small, hand-verified lookup tables so the test profile runs offline. Every identifier
and label was checked against the EBI OLS4 API (HPO, MONDO), the HGNC REST API and the
RxNav REST API on 2026-11-11. They are a subset, not a release: a real run replaces
them with full ontology releases through OAK (`make vocab`, not yet implemented).

| File | Columns | Source |
| --- | --- | --- |
| `hp_terms.tsv` | id, label, obsolete, replaced_by, kind (feature or onset) | HPO via OLS |
| `diseases.tsv` | mondo_id, label, orphanet, omim, gene_symbol, hgnc_id, hpo_pool | MONDO xrefs via OLS, HGNC |
| `onset_bands.tsv` | band_text (normalised), hpo_id, note | curated; see note column for assumptions |
| `lay_terms.tsv` | text (normalised), hpo_id | curated lay phrases used in free-text answers |
| `drug_lexicon.tsv` | text (normalised), rxcui, label | RxNav |
| `survey_lookups/<registry>_<form>_<version>.tsv` | question_id, hpo_id | curated per survey version |
