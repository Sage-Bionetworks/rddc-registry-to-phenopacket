#!/usr/bin/env nextflow
/*
 * rddc-registry-to-phenopacket: registry exports -> RegistryRecord (LinkML-Map) -> GA4GH Phenopacket v2.
 *
 * One samplesheet row per registry export:
 *   registry       short name, used in output paths and in survey lookup file names
 *   format         json (one hierarchical export file) | csv (one wide table, one row per participant)
 *   data           the export file
 *   source_schema  LinkML schema describing the export (schema/sources/)
 *   transform      LinkML-Map specification to RegistryRecord (mappings/)
 *   source_type    class in source_schema that the data file instantiates
 *   truth          optional ground-truth JSONL for the round-trip check (synthetic data only)
 */

include { LINKML_MAP           } from './modules/local/linkml_map/main.nf'
include { CROSSWALK            } from './modules/local/crosswalk/main.nf'
include { BUILD_PHENOPACKETS   } from './modules/local/build_phenopackets/main.nf'
include { VALIDATE_PHENOPACKETS } from './modules/local/validate_phenopackets/main.nf'
include { ROUNDTRIP_CHECK      } from './modules/local/roundtrip_check/main.nf'

def resolvePath(String p) {
    def f = file(p)
    if (f.isAbsolute()) return f
    def root = params.samplesheet_root ? file(params.samplesheet_root) : launchDir
    return file("${root}/${p}", checkIfExists: true)
}

workflow {
    if (!params.samplesheet) error "--samplesheet is required"
    if (!params.outdir)      error "--outdir is required"

    assets        = channel.value(file(params.assets, checkIfExists: true, type: 'dir'))
    target_schema = channel.value(file(params.target_schema, checkIfExists: true))

    rows = channel.fromPath(params.samplesheet, checkIfExists: true)
        .splitCsv(header: true, strip: true)
        .map { row ->
            if (!(row.format in ['json', 'csv'])) error "format must be json or csv (registry ${row.registry})"
            tuple(row.registry, row.format, resolvePath(row.data), resolvePath(row.source_schema),
                  resolvePath(row.transform), row.source_type, row.truth ? resolvePath(row.truth) : [])
        }

    LINKML_MAP(rows.map { r -> r[0..5] }, target_schema)
    CROSSWALK(LINKML_MAP.out.records, assets)
    BUILD_PHENOPACKETS(CROSSWALK.out.resolved, assets)

    if (params.pxf_jar) {
        VALIDATE_PHENOPACKETS(BUILD_PHENOPACKETS.out.phenopackets, channel.value(file(params.pxf_jar, checkIfExists: true)))
    }

    with_truth = rows.filter { r -> r[6] }.map { r -> tuple(r[0], r[6]) }
    ROUNDTRIP_CHECK(
        BUILD_PHENOPACKETS.out.phenopackets.join(CROSSWALK.out.unmapped).join(with_truth)
    )

    CROSSWALK.out.unmapped
        .map { reg, f -> f }
        .collectFile(name: 'unmapped_all.tsv', keepHeader: true, skip: 1, storeDir: "${params.outdir}/summary")
    BUILD_PHENOPACKETS.out.report
        .map { reg, f -> f }
        .collectFile(name: 'build_report_all.tsv', keepHeader: true, skip: 1, storeDir: "${params.outdir}/summary")
    ROUNDTRIP_CHECK.out.report
        .map { reg, f -> f }
        .collectFile(name: 'roundtrip_all.tsv', keepHeader: true, skip: 1, storeDir: "${params.outdir}/summary")

    LINKML_MAP.out.versions.mix(BUILD_PHENOPACKETS.out.versions)
        .map { f -> f.text }
        .unique()
        .collectFile(name: 'software_versions.yml', storeDir: "${params.outdir}/pipeline_info")
}
