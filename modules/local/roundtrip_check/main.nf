// Compare phenopackets with the generator's ground truth (synthetic fixtures only).
process ROUNDTRIP_CHECK {
    tag "$registry"
    label 'process_single'
    publishDir path: { "${params.outdir}/${registry}" }, mode: 'copy'

    input:
    tuple val(registry), path(phenopackets), path(unmapped), path(truth)

    output:
    tuple val(registry), path("${registry}.roundtrip.tsv"), emit: report

    script:
    def strict = params.strict_roundtrip ? '--strict' : ''
    """
    roundtrip_check.py \\
        --truth $truth \\
        --registry $registry \\
        --phenopackets $phenopackets \\
        --unmapped $unmapped \\
        --out ${registry}.roundtrip.tsv \\
        $strict
    """
}
