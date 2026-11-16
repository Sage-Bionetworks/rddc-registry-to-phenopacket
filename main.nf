#!/usr/bin/env nextflow
/*
 * rddc-registry-to-phenopacket: registry exports -> RegistryRecord (LinkML-Map) -> GA4GH Phenopacket v2.
 *
 * Input: the batch's Croissant sidecar (--sidecar, _sidecar.json; rddc-model), one registry
 * export per batch, as the other RDDC pipelines take their input. SIDECAR_INTAKE stages the
 * files the sidecar lists and checks their checksums. The batch's source (sourceId) selects
 * its registered mapping in --sources (mappings/sources.yaml): which file is the export, and
 * the source schema, LinkML-Map transform and source type. The sidecar's subjects are
 * reconciled with the export's participants.
 *
 * --truth   ground-truth JSONL for the round-trip check (synthetic fixtures only; not part of a deposit)
 * --vocab   directory of release tables from bin/build_vocab.py (make vocab); defaults to assets/,
 *           which holds a committed subset so the test profile runs offline.
 * --hp_json hp.json for OAK graph checks in validation (slow to load; off by default).
 */

include { SIDECAR_INTAKE        } from './subworkflows/local/sidecar_intake/main.nf'
include { CHECK_EXPORT          } from './modules/local/check_export/main.nf'
include { LINKML_MAP            } from './modules/local/linkml_map/main.nf'
include { CROSSWALK             } from './modules/local/crosswalk/main.nf'
include { RECONCILE_SUBJECTS    } from './modules/local/reconcile_subjects/main.nf'
include { BUILD_PHENOPACKETS    } from './modules/local/build_phenopackets/main.nf'
include { VALIDATE_PHENOPACKETS } from './modules/local/validate_phenopackets/main.nf'
include { VALIDATE_PXF          } from './modules/local/validate_pxf/main.nf'
include { ROUNDTRIP_CHECK       } from './modules/local/roundtrip_check/main.nf'

// The registered mapping of a source (mappings/sources.yaml), with paths resolved.
def sourceConfig(String sourceId) {
    def sources = new org.yaml.snakeyaml.Yaml().load(file(params.sources, checkIfExists: true).text) as Map
    def s = sources[sourceId]
    if (!s) error "source ${sourceId} has no registered mapping in ${params.sources} (registered: ${sources.keySet()})"
    ['registry', 'file', 'format', 'source_schema', 'transform', 'source_type'].each { k ->
        if (!s[k]) error "${params.sources}: ${sourceId} needs '${k}'"
    }
    if (!(s.format in ['json', 'csv'])) error "${params.sources}: ${sourceId} format must be json or csv"
    return s + [source_schema: file("${projectDir}/${s.source_schema}", checkIfExists: true),
                transform    : file("${projectDir}/${s.transform}", checkIfExists: true)]
}

def isExport(Map meta, Map src) {
    return meta.additionalType == src.file.additionalType && meta.encodingFormat == src.file.encodingFormat
}

def intakeRow(Map meta, String route, String reason) {
    return [meta.id, meta.name, meta.additionalType, meta.encodingFormat ?: '', meta.subjectIds.size(),
            route, reason].join('\t') + '\n'
}

workflow {
    if (!params.sidecar) error "--sidecar (the batch's _sidecar.json) is required"
    if (!params.outdir)  error "--outdir is required"

    assets        = channel.value(file(params.assets, checkIfExists: true, type: 'dir'))
    vocab         = channel.value(file(params.vocab ?: params.assets, checkIfExists: true, type: 'dir'))
    hp_json       = channel.value(params.hp_json ? file(params.hp_json, checkIfExists: true) : file("${projectDir}/assets/NO_HP_JSON"))
    target_schema = channel.value(file(params.target_schema, checkIfExists: true))

    SIDECAR_INTAKE(file(params.sidecar, checkIfExists: true))
    batch = SIDECAR_INTAKE.out.batch
    source = batch.map { b -> sourceConfig(b.sourceId as String) }

    // The registered export is mapped; its data dictionary (DocumentationFile) is kept for
    // reference (the source schema is compiled from it offline); anything else is skipped.
    routed = SIDECAR_INTAKE.out.files.combine(source).map { meta, f, src ->
        def (r, reason) = isExport(meta, src) ? ['map', ''] :
            meta.additionalType == 'DocumentationFile' ? ['documentation', ''] :
            ['skipped', 'not_the_registered_export']
        [meta + [route: r, route_reason: reason], f]
    }
    export = routed.filter { meta, _f -> meta.route == 'map' }

    intake = routed.map { meta, _f -> intakeRow(meta, meta.route, meta.route_reason) }
        .mix(SIDECAR_INTAKE.out.rejected.map { meta, reason -> intakeRow(meta, 'rejected', reason) })
        .mix(SIDECAR_INTAKE.out.sets.map { meta -> intakeRow(meta, 'file_set', '') })
        .collectFile(name: 'intake.tsv', storeDir: "${params.outdir}/intake", sort: true,
                     seed: "file_id\tname\tclass\tencoding_format\tsubject_count\troute\treason\n")
    batch.map { b -> groovy.json.JsonOutput.prettyPrint(groovy.json.JsonOutput.toJson(b.findAll { k, _v -> k != 'subjects' })) + '\n' }
        .collectFile(name: 'batch.json', storeDir: "${params.outdir}/intake")

    CHECK_EXPORT(intake, export.count())

    mapping_input = export.combine(source).combine(CHECK_EXPORT.out.ok)
        .map { _meta, f, src, _ok -> tuple(src.registry, src.format, f, src.source_schema, src.transform, src.source_type) }

    LINKML_MAP(mapping_input, target_schema)
    CROSSWALK(LINKML_MAP.out.records, assets, vocab)

    // The sidecar's participant IDs (idSystem contributor), one per line, per registry.
    subjects = batch.combine(source)
        .map { b, src ->
            def ids = b.subjects.findAll { s -> s.idSystem == 'contributor' }*.subjectId
            ["${src.registry}.sidecar_subjects.txt", ids.join('\n') + (ids ? '\n' : '')]
        }
        .collectFile()
        .map { f -> tuple(f.name - '.sidecar_subjects.txt', f) }
    RECONCILE_SUBJECTS(CROSSWALK.out.resolved.join(subjects))

    BUILD_PHENOPACKETS(CROSSWALK.out.resolved, assets, vocab)
    VALIDATE_PHENOPACKETS(BUILD_PHENOPACKETS.out.phenopackets, vocab, hp_json)

    if (params.pxf_jar) {
        VALIDATE_PXF(BUILD_PHENOPACKETS.out.phenopackets, channel.value(file(params.pxf_jar, checkIfExists: true)))
    }

    if (params.truth) {
        truth = source.map { src -> tuple(src.registry, file(params.truth, checkIfExists: true)) }
        ROUNDTRIP_CHECK(BUILD_PHENOPACKETS.out.phenopackets.join(CROSSWALK.out.unmapped).join(truth))
        ROUNDTRIP_CHECK.out.report
            .map { _reg, f -> f }
            .collectFile(name: 'roundtrip_all.tsv', keepHeader: true, skip: 1, storeDir: "${params.outdir}/summary")
    }

    CROSSWALK.out.unmapped
        .map { _reg, f -> f }
        .collectFile(name: 'unmapped_all.tsv', keepHeader: true, skip: 1, storeDir: "${params.outdir}/summary")
    BUILD_PHENOPACKETS.out.report
        .map { _reg, f -> f }
        .collectFile(name: 'build_report_all.tsv', keepHeader: true, skip: 1, storeDir: "${params.outdir}/summary")
    VALIDATE_PHENOPACKETS.out.report
        .map { _reg, f -> f }
        .collectFile(name: 'validation_all.tsv', keepHeader: true, skip: 1, storeDir: "${params.outdir}/summary")

    LINKML_MAP.out.versions.mix(BUILD_PHENOPACKETS.out.versions)
        .map { f -> f.text }
        .unique()
        .collectFile(name: 'software_versions.yml', storeDir: "${params.outdir}/pipeline_info")
}
