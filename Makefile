# Common tasks. Tools go into .venv/ and .tools/ (gitignored); nothing is installed system-wide.
SHELL := /bin/bash
PXF_VERSION ?= 1.0.0
export NXF_HOME ?= $(CURDIR)/.tools/nxf-home
NEXTFLOW := $(CURDIR)/.tools/nextflow
PXF_JAR  := $(CURDIR)/.tools/phenopacket-tools-cli-$(PXF_VERSION)/phenopacket-tools-cli-$(PXF_VERSION).jar
PY := $(CURDIR)/.venv/bin/python

.PHONY: tools venv data spec lint test nf-test nf-full nf-test-docker validate vocab assets-subset image clean sidecars nf-test-errors

tools: venv .tools/nextflow $(PXF_JAR)   ## python env, nextflow and phenopacket-tools into .venv/ and .tools/

venv: .venv/bin/python
.venv/bin/python: pyproject.toml
	uv venv -q --allow-existing .venv --python 3.12 && uv pip install -q --python .venv/bin/python -r pyproject.toml
	touch $@

.tools/nextflow:
	mkdir -p .tools
	curl -fsSL https://get.nextflow.io -o $@ && chmod +x $@ && $@ -version >/dev/null

$(PXF_JAR):
	mkdir -p .tools && cd .tools && curl -fsSL -o pxf.zip \
	  https://github.com/phenopackets/phenopacket-tools/releases/download/v$(PXF_VERSION)/phenopacket-tools-cli-$(PXF_VERSION)-distribution.zip \
	  && unzip -q -o pxf.zip && rm pxf.zip

data: venv   ## regenerate the synthetic fixtures (two registries + truth) into tests/data
	$(PY) bin/gen_registry_data.py --assets assets --outdir tests/data -n 24 --seed 7
	$(MAKE) sidecars   # the data changed, so the sidecars' checksums and subjects did too

spec: venv   ## recompile the wide-table source schema and mapping spec from the data dictionary
	$(PY) bin/gen_wide_spec.py tests/data/redcaplike/dictionary.csv --registry redcaplike \
	  --schema-out schema/sources/redcaplike_wide.yaml --spec-out mappings/redcaplike_to_record.transform.yaml

lint: venv   ## lint schemas and validate both mapping specs against source and target
	.venv/bin/linkml-lint --ignore-warnings schema/registry_record.yaml
	.venv/bin/linkml-map validate-spec --strict --source-schema schema/sources/nordlike_export.yaml --target-schema schema/registry_record.yaml mappings/nordlike_to_record.transform.yaml
	.venv/bin/linkml-map validate-spec --strict --source-schema schema/sources/redcaplike_wide.yaml --target-schema schema/registry_record.yaml mappings/redcaplike_to_record.transform.yaml

test: venv   ## the python stages on the fixtures, no Nextflow; strict round-trip
	tests/run_tests.sh

# One batch (sidecar) per run; the fixtures are two batches, one per registry.
BATCHES := nordlike redcaplike
RDDC_MODEL ?= ../rddc-model

sidecars: venv   ## rewrite the test batches' _sidecar.json and validate them against rddc-model ($(RDDC_MODEL))
	$(PY) -I tests/make_sidecars.py --context $(RDDC_MODEL)/examples/ccda_document_set.json \
	  --schema $(RDDC_MODEL)/schema/generated/rddc_sidecar.schema.json

nf-test: .tools/nextflow venv   ## full pipeline via Nextflow on each test batch, no container
	for b in $(BATCHES); do \
	  $(NEXTFLOW) run . -profile test,local --sidecar tests/data/$$b/_sidecar.json --outdir results/test/$$b || exit 1; \
	done

nf-test-errors: .tools/nextflow venv   ## intake rejection: a wrong checksum on the export stops the run after intake.tsv
	! $(NEXTFLOW) run . -profile test,local --sidecar tests/data/nordlike/_sidecar.errors.json --outdir results/test-errors
	grep -q $$'export.json\tTabularFile\tapplication/json\t24\trejected\tchecksum_mismatch_md5' results/test-errors/intake/intake.tsv
	test ! -e results/test-errors/nordlike/phenopackets
	@echo "rejected export stopped the run; intake.tsv written"

nf-test-docker: .tools/nextflow image
	for b in $(BATCHES); do \
	  $(NEXTFLOW) run . -profile test,docker --sidecar tests/data/$$b/_sidecar.json --outdir results/test-docker/$$b || exit 1; \
	done

validate: $(PXF_JAR)   ## phenopacket-tools (Java) validation of the last nf-test results; the Python validator runs inside the pipeline
	java -jar $(PXF_JAR) validate results/test/*/*/phenopackets/*.phenopacket.json

# Full vocabulary releases (not committed): hp.json, Mondo SSSOM cross-references, HGNC complete set.
vocab/hp.json:
	mkdir -p vocab && curl -fsSL -o $@ http://purl.obolibrary.org/obo/hp.json
vocab/mondo.sssom.tsv:
	mkdir -p vocab && curl -fsSL -o $@ http://purl.obolibrary.org/obo/mondo/mappings/mondo.sssom.tsv
vocab/hgnc_complete_set.txt:
	mkdir -p vocab && curl -fsSL -o $@ https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt

vocab: venv vocab/hp.json vocab/mondo.sssom.tsv vocab/hgnc_complete_set.txt   ## build release tables into vocab/tables (OAK; ~1 min)
	$(PY) bin/build_vocab.py --hp-json vocab/hp.json --mondo-sssom vocab/mondo.sssom.tsv --hgnc vocab/hgnc_complete_set.txt --out vocab/tables

assets-subset: vocab   ## re-derive the committed assets/ vocabulary subset as a slice of the release
	$(PY) bin/build_vocab.py --hp-json vocab/hp.json --mondo-sssom vocab/mondo.sssom.tsv --hgnc vocab/hgnc_complete_set.txt \
	  --out assets --subset-from assets/hp_terms.tsv assets/diseases.tsv assets/lay_terms.tsv assets/survey_lookups/*.tsv

nf-full: .tools/nextflow venv vocab   ## pipeline on the fixtures with the full releases and OAK graph checks (round trip not strict)
	for b in $(BATCHES); do \
	  $(NEXTFLOW) run . -profile test,local --sidecar tests/data/$$b/_sidecar.json --outdir results/full/$$b \
	    --vocab vocab/tables --hp_json vocab/hp.json --strict_roundtrip false || exit 1; \
	done

image:   ## build rddc-registry-to-phenopacket:dev (not yet exercised)
	docker build -t rddc-registry-to-phenopacket:dev .

clean:
	rm -rf work results .nextflow .nextflow.log*
