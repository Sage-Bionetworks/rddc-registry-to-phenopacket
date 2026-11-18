"""Point the pipeline at the batch's sidecar, before Nextflow starts.

The input dataset is a deposited batch: its files plus `_sidecar.json` at the batch root. The
pipeline finds every other file from the sidecar, so the only parameter set here is
`sidecar`, the full S3 path of that file. A run without exactly one input dataset that has a
root-level `_sidecar.json` is refused before any compute starts.

The sidecar is looked for in the listing of the input datasets (`ds.input_files()`), not in
`ds.files`: that table holds only files matched to samples, and a batch has no samples.
Datasets chosen in a run form would be inputs too; only the batch has a sidecar.
"""

from cirro.helpers.preprocess_dataset import PreprocessDataset


def object_key(path):
    """An S3 path or key without scheme and bucket, so listings in either form compare."""
    return path.split("://", 1)[1].split("/", 1)[1] if "://" in path else path.lstrip("/")


def find_sidecar(data_paths, files):
    """The `<dataPath>/_sidecar.json` that exists, if exactly one input dataset has one."""
    keys = {object_key(f) for f in files}
    candidates = [p.rstrip("/") + "/_sidecar.json" for p in data_paths]
    found = [c for c in candidates if object_key(c) in keys]
    if not found:
        raise ValueError("no input dataset has a _sidecar.json at its root")
    if len(found) > 1:
        raise ValueError(f"more than one input dataset has a _sidecar.json: {found}")
    return found[0]


def main():
    ds = PreprocessDataset.from_running()
    data_paths = [d["dataPath"] for d in ds.metadata["inputs"]]
    ds.add_param("sidecar", find_sidecar(data_paths, list(ds.input_files()["file"])))


if __name__ == "__main__":
    main()
