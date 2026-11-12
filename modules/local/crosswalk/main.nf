// Resolve codes and texts to HPO, MONDO, HGNC and RxNorm; report everything that did not resolve.
process CROSSWALK {
    tag "$registry"
    label 'process_single'
    publishDir path: { "${params.outdir}/${registry}" }, mode: 'copy'

    input:
    tuple val(registry), path(records)
    path assets
    path vocab

    output:
    tuple val(registry), path("${registry}.resolved.jsonl"), emit: resolved
    tuple val(registry), path("${registry}.unmapped.tsv"),   emit: unmapped

    script:
    """
    crosswalk.py \\
        --records $records \\
        --assets $assets \\
        --vocab $vocab \\
        --registry $registry \\
        --out ${registry}.resolved.jsonl \\
        --unmapped ${registry}.unmapped.tsv
    """
}
