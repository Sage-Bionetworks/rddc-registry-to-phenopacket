# Not yet built or exercised. Python stages plus Java for phenopacket-tools validation.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends default-jre-headless && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml /tmp/pyproject.toml
RUN pip install --no-cache-dir "linkml-map>=0.6.0,<0.7" "linkml>=1.9" "phenopackets>=2.0.2,<3" "pyyaml>=6" "oaklib>=0.7,<0.8"
ENV PYTHONDONTWRITEBYTECODE=1
