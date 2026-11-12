# Common tasks. Tools go into .venv/ and .tools/ (gitignored); nothing is installed system-wide.
SHELL := /bin/bash
PXF_VERSION ?= 1.0.0
export NXF_HOME ?= $(CURDIR)/.tools/nxf-home
NEXTFLOW := $(CURDIR)/.tools/nextflow
PXF_JAR  := $(CURDIR)/.tools/phenopacket-tools-cli-$(PXF_VERSION)/phenopacket-tools-cli-$(PXF_VERSION).jar
PY := $(CURDIR)/.venv/bin/python

.PHONY: tools venv data spec lint test nf-test nf-test-docker validate image clean

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

spec: venv   ## recompile the wide-table source schema and mapping spec from the data dictionary
	$(PY) bin/gen_wide_spec.py tests/data/redcaplike/dictionary.csv --registry redcaplike \
	  --schema-out schema/sources/redcaplike_wide.yaml --spec-out mappings/redcaplike_to_record.transform.yaml

lint: venv   ## lint schemas and validate both mapping specs against source and target
	.venv/bin/linkml-lint --ignore-warnings schema/registry_record.yaml
	.venv/bin/linkml-map validate-spec --strict --source-schema schema/sources/nordlike_export.yaml --target-schema schema/registry_record.yaml mappings/nordlike_to_record.transform.yaml
	.venv/bin/linkml-map validate-spec --strict --source-schema schema/sources/redcaplike_wide.yaml --target-schema schema/registry_record.yaml mappings/redcaplike_to_record.transform.yaml

test: venv   ## the python stages on the fixtures, no Nextflow; strict round-trip
	tests/run_tests.sh

nf-test: .tools/nextflow venv   ## full pipeline via Nextflow, no container
	$(NEXTFLOW) run . -profile test,local --outdir results/test

nf-test-docker: .tools/nextflow image
	$(NEXTFLOW) run . -profile test,docker --outdir results/test-docker

validate: $(PXF_JAR)   ## phenopacket-tools validation of the last nf-test results
	java -jar $(PXF_JAR) validate results/test/*/phenopackets/*.phenopacket.json

image:   ## build rddc-registry-to-phenopacket:dev (not yet exercised)
	docker build -t rddc-registry-to-phenopacket:dev .

clean:
	rm -rf work results .nextflow .nextflow.log*
