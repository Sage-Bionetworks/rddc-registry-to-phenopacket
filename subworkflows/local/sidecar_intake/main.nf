// Vendored from Sage-Bionetworks/rddc-genomics-workflows, subworkflows/local/sidecar_intake/main.nf
// (commit e066dac, branch report-findings-dev). Keep the copies in sync until it moves to a shared repo.
/*
 * SIDECAR_INTAKE: the files of a batch, described by its Croissant sidecar (rddc-model).
 *
 * Reads _sidecar.json, resolves each FileObject's contentUrl against the sidecar's location
 * (local path or s3://), stages the file and checks its checksums. Pipelines choose what to
 * process from meta.additionalType and the other fields; nothing here is pipeline-specific.
 *
 * File sets (cr:FileSet) group files. A set that lists its members (hasPart) is reported in
 * `sets`, and its fields are copied to each member's meta.fileSet (e.g. conformsTo, exportTime
 * of a FhirBulkExport). A set that only gives patterns (includes) is rejected: its files are
 * not listed, so they cannot be checked against checksums.
 *
 * emit:
 *   files     [meta, file] for every FileObject whose checksums match
 *   rejected  [meta, reason] for entries that cannot be processed (checksum mismatch, a
 *             contentUrl outside the batch, a missing md5, a file set without listed files)
 *   sets      [meta] for every file set that lists its members (its fields in meta.fileSet)
 *   batch     the batch header (map), once
 *
 * meta: id (file UUID), urn, name, contentUrl, additionalType (without "rddc:"),
 *       encodingFormat, compression, documentType, resourceType, subjectIds, subjects
 *       ([subjectId, idSystem] for each subjectId), reportDocuments (file UUIDs), md5, sha256,
 *       fileSet (map of the set's fields, or null), batch (header map)
 */

include { VERIFY_CHECKSUM } from '../../../modules/local/verify_checksum/main.nf'

// JsonSlurperClassic, not JsonSlurper: JsonSlurper's lazy maps fill themselves in on first
// read, and these maps are shared by every file's meta, which Nextflow hashes in parallel
// (ConcurrentModificationException).

def stripUrn(String s) {
    return s?.startsWith('urn:uuid:') ? s.substring(9) : s
}

def batchHeader(Map doc, String location) {
    return [
        urn          : doc['@id'],
        name         : doc.name,
        sourceId     : doc.sourceId,
        batchId      : doc.batchId,
        contributorId: doc.contributorId,
        dateCreated  : doc.dateCreated,
        conformsTo   : doc.conformsTo instanceof List ? doc.conformsTo : [doc.conformsTo],
        sensitivity  : doc.sensitivity ?: [:],
        subjects     : doc.subjects ?: [],
        location     : location,
    ]
}

def typesOf(Map item) {
    return item['@type'] instanceof List ? item['@type'] : [item['@type']]
}

def setFields(Map item) {
    // The set's own fields, for its members: everything except identity and membership.
    return item.findAll { k, _v -> !(k in ['@type', 'hasPart', 'includes', 'excludes']) } +
        [id: stripUrn(item['@id']), additionalType: (item.additionalType ?: '').replaceFirst(/^rddc:/, '')]
}

// One entry per distribution item: [kind, meta, contentPath or null, problem or null], where
// kind is 'file' or 'set'.
def parseSidecar(sidecarPath) {
    def doc = new groovy.json.JsonSlurperClassic().parseText(sidecarPath.text)
    if (!(doc instanceof Map) || !doc.distribution) {
        error "${sidecarPath}: not a sidecar with a distribution"
    }
    def root = sidecarPath.parent
    def batch = batchHeader(doc, root.toUriString())
    def idSystems = (doc.subjects ?: []).collectEntries { s -> [(s.subjectId): s.idSystem] }

    // Which set each listed file belongs to.
    def setOf = [:]
    doc.distribution.findAll { item -> 'cr:FileSet' in typesOf(item) }.each { set ->
        (set.hasPart ?: []).each { ref -> setOf[ref['@id']] = setFields(set) }
    }

    return doc.distribution.collect { item ->
        def meta = [
            id             : stripUrn(item['@id']),
            urn            : item['@id'],
            name           : item.name,
            contentUrl     : item.contentUrl,
            additionalType : (item.additionalType ?: '').replaceFirst(/^rddc:/, ''),
            encodingFormat : item.encodingFormat,
            compression    : item.compression,
            documentType   : item.documentType,
            resourceType   : item.resourceType,
            subjectIds     : item.subjectIds ?: [],
            subjects       : (item.subjectIds ?: []).collect { sid -> [subjectId: sid, idSystem: idSystems[sid]] },
            reportDocuments: (item.reportDocuments ?: []).collect { ref -> stripUrn(ref['@id']) },
            md5            : item.md5,
            sha256         : item.sha256,
            fileSet        : setOf[item['@id']],
            batch          : batch,
        ]
        def types = typesOf(item)
        if ('cr:FileSet' in types) {
            meta.fileSet = setFields(item)   // a set's own fields (conformsTo, exportTime, …)
            return item.hasPart ? ['set', meta, null, null] : ['set', meta, null, 'file_set_not_listed']
        }
        if (!('cr:FileObject' in types)) {
            return ['file', meta, null, 'not_a_file_object']
        }
        def url = item.contentUrl as String
        // contentUrl is an object key relative to the batch prefix: no scheme, no absolute
        // path, no "..". Anything else could reach outside the batch.
        if (!url || url.contains('://') || url.startsWith('/') || url.split('/').contains('..')) {
            return ['file', meta, null, 'content_url_outside_batch']
        }
        if (!item.md5) {
            return ['file', meta, null, 'missing_md5']
        }
        return ['file', meta, root.resolve(url), null]
    }
}

workflow SIDECAR_INTAKE {
    take:
    sidecar   // path to _sidecar.json

    main:
    entries = channel.of(sidecar).flatMap { p -> parseSidecar(p) }

    usable = entries.filter { kind, _meta, _path, problem -> kind == 'file' && problem == null }
        .map { _kind, meta, path, _problem -> [meta, file(path, checkIfExists: true)] }
    unusable = entries.filter { _kind, _meta, _path, problem -> problem != null }
        .map { _kind, meta, _path, problem -> [meta, problem] }
    listed_sets = entries.filter { kind, _meta, _path, problem -> kind == 'set' && problem == null }
        .map { _kind, meta, _path, _problem -> meta }

    VERIFY_CHECKSUM(usable)

    files = VERIFY_CHECKSUM.out.checked
        .filter { _meta, _data, status -> status.trim() == 'ok' }
        .map { meta, data, _status -> [meta, data] }
    mismatched = VERIFY_CHECKSUM.out.checked
        .filter { _meta, _data, status -> status.trim() != 'ok' }
        .map { meta, _data, status -> [meta, "checksum_${status.trim().replace(':', '_')}"] }

    emit:
    files    = files
    rejected = unusable.mix(mismatched)
    sets     = listed_sets
    batch    = channel.of(sidecar).map { p -> batchHeader(new groovy.json.JsonSlurperClassic().parseText(p.text), p.parent.toUriString()) }
}
