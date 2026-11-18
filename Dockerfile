# Runtime for every process: the Python stages, plus Java for phenopacket-tools validation
# (VALIDATE_PXF, only when --pxf_jar is given). bin/ is not copied: Nextflow puts it on PATH.
# The Python packages are pinned to the versions the tests pass with (pyproject.toml gives
# the allowed ranges). procps gives Nextflow `ps` for task metrics.
FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends default-jre-headless procps \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "linkml-map==0.6.0" "linkml==1.12.1" "phenopackets==2.0.2.post5" \
    "pyyaml==6.0.3" "oaklib==0.7.4"
ENV PYTHONDONTWRITEBYTECODE=1
