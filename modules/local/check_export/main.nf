// Stop the run, after intake/intake.tsv is written, when the batch does not have exactly one
// usable file matching the source's registered export (missing, rejected at intake, or several).
process CHECK_EXPORT {
    label 'process_single'

    input:
    path intake            // intake.tsv, so it is published before a failure
    val  n_export          // files that matched the registered export and passed intake

    output:
    val true, emit: ok

    script:
    """
    if [ ${n_export} -ne 1 ]; then
        echo "expected exactly one usable registry export in the batch, found ${n_export}; intake report:" >&2
        cat ${intake} >&2
        exit 1
    fi
    """
}
