// One phenopacket and one extras file per record, plus a per-record build report.
process BUILD_PHENOPACKETS {
    tag "$registry"
    label 'process_single'
    publishDir path: { "${params.outdir}/${registry}" }, mode: 'copy', saveAs: { f -> f.replaceFirst("^${registry}/", '') }

    input:
    tuple val(registry), path(resolved)
    path assets

    output:
    tuple val(registry), path("${registry}/phenopackets"),    emit: phenopackets
    tuple val(registry), path("${registry}/extras"),          emit: extras
    tuple val(registry), path("${registry}/build_report.tsv"), emit: report
    path "versions.yml",                                       emit: versions

    script:
    """
    build_phenopackets.py \\
        --resolved $resolved \\
        --assets $assets \\
        --outdir $registry \\
        --created-by "${workflow.manifest.name} ${workflow.manifest.version}"

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        phenopackets: \$(python -c "import importlib.metadata as m; print(m.version('phenopackets'))")
    END_VERSIONS
    """
}
