// Validate with the phenopacket-tools CLI (Java). Runs only when --pxf_jar is given.
// NOT YET EXERCISED in this environment: the jar could not be run during scaffolding,
// so check the `validate` subcommand's flags against `java -jar <jar> validate --help`.
process VALIDATE_PXF {
    tag "$registry"
    label 'process_single'
    publishDir path: { "${params.outdir}/${registry}" }, mode: 'copy'

    input:
    tuple val(registry), path(phenopackets)
    path jar

    output:
    tuple val(registry), path("${registry}.validation.txt"), emit: report

    script:
    """
    java -jar $jar validate ${phenopackets}/*.phenopacket.json > ${registry}.validation.txt 2>&1
    """
}
