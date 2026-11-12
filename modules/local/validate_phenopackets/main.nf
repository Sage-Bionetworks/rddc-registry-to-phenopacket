// Validate phenopackets in Python: schema parse, required metadata, resource coverage, HPO term
// checks against the release tables, and (with --hp_json) ancestor conflicts through OAK.
process VALIDATE_PHENOPACKETS {
    tag "$registry"
    label 'process_single'
    publishDir path: { "${params.outdir}/${registry}" }, mode: 'copy'

    input:
    tuple val(registry), path(phenopackets)
    path vocab
    path hp_json

    output:
    tuple val(registry), path("${registry}.validation.tsv"), emit: report

    script:
    def strict = params.strict_validation ? '--strict' : ''
    def graph  = hp_json.name != 'NO_HP_JSON' ? "--hp-json $hp_json" : ''
    """
    validate_phenopackets.py \\
        --phenopackets $phenopackets \\
        --vocab $vocab \\
        $graph \\
        --out ${registry}.validation.tsv \\
        $strict
    """
}
