// Reconcile the export's participants with the subjects the batch's sidecar lists.
process RECONCILE_SUBJECTS {
    tag "$registry"
    label 'process_single'
    publishDir path: { "${params.outdir}/${registry}" }, mode: 'copy'

    input:
    tuple val(registry), path(records), path(subjects)

    output:
    tuple val(registry), path("${registry}.subjects.tsv"), emit: report

    script:
    def strict = params.strict_validation.toString() == 'true' ? '--strict' : ''
    """
    reconcile_subjects.py --records $records --subjects $subjects --out ${registry}.subjects.tsv $strict
    """
}
