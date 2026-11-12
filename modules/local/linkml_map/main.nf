// Map one registry export to RegistryRecord objects with LinkML-Map.
// JSON exports map as one RegistryExport container; CSV exports map row by row to JSON Lines.
process LINKML_MAP {
    tag "$registry"
    label 'process_single'
    publishDir path: { "${params.outdir}/${registry}" }, mode: 'copy', pattern: '*.records.*'

    input:
    tuple val(registry), val(format), path(data), path(source_schema), path(transform), val(source_type)
    path target_schema

    output:
    tuple val(registry), path("${registry}.records.*"), emit: records
    path "versions.yml",                                  emit: versions

    script:
    def ext = format == 'json' ? 'json' : 'jsonl'
    """
    linkml-map map-data \\
        -T $transform \\
        -s $source_schema \\
        --target-schema $target_schema \\
        --source-type $source_type \\
        --strict \\
        -f $ext \\
        -o ${registry}.records.${ext} \\
        $data

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        linkml-map: \$(python -c "import importlib.metadata as m; print(m.version('linkml-map'))")
        linkml-runtime: \$(python -c "import importlib.metadata as m; print(m.version('linkml-runtime'))")
    END_VERSIONS
    """
}
