#!/usr/bin/env python3
"""Build one GA4GH Phenopacket v2 per resolved RegistryRecord, plus an extras file.

The phenopacket holds only what the schema can express with a resolved term:
phenotypic features (present or excluded, with onset), diseases, a genomic
interpretation when the registry marks genetic confirmation, medications with an
RxNorm agent, and uploaded documents as files. Everything else goes, verbatim, to
<id>.extras.json so the gap is visible: respondent, birth year, instrument scores,
treatment response text, family history, unknown answers, unresolved values.
"""
import argparse, csv, json
from datetime import datetime, timezone
from pathlib import Path
import yaml
import phenopackets as pp
from google.protobuf.json_format import MessageToJson
from google.protobuf.timestamp_pb2 import Timestamp

RESOURCES = {
    "HP": dict(id="hp", name="human phenotype ontology", url="http://purl.obolibrary.org/obo/hp.owl", namespace_prefix="HP", iri_prefix="http://purl.obolibrary.org/obo/HP_"),
    "MONDO": dict(id="mondo", name="Mondo Disease Ontology", url="http://purl.obolibrary.org/obo/mondo.owl", namespace_prefix="MONDO", iri_prefix="http://purl.obolibrary.org/obo/MONDO_"),
    "HGNC": dict(id="hgnc", name="HUGO Gene Nomenclature Committee", url="https://www.genenames.org", namespace_prefix="HGNC", iri_prefix="https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/HGNC:"),
    "RxNorm": dict(id="rxnorm", name="RxNorm", url="https://www.nlm.nih.gov/research/umls/rxnorm", namespace_prefix="RxNorm", iri_prefix="https://mor.nlm.nih.gov/RxNav/search?searchBy=RXCUI&searchTerm="),
}
SEX = {"FEMALE": pp.Sex.FEMALE, "MALE": pp.Sex.MALE, "OTHER_SEX": pp.Sex.OTHER_SEX, "UNKNOWN_SEX": pp.Sex.UNKNOWN_SEX}


def oc(id_, label):
    return pp.OntologyClass(id=id_, label=label or "")


def onset_te(hpo_id, hp):
    return pp.TimeElement(ontology_class=oc(hpo_id, hp.get(hpo_id, {}).get("label", ""))) if hpo_id else None


def build(rec, hp, versions, created_by):
    rid, registry = rec["id"], rec["registry"]
    used = set()
    extras = {"registry": registry, "id": rid, "respondent": rec.get("respondent"), "birth_year": rec.get("birth_year"),
              "country": rec.get("country"), "unknown_answers": [], "conflicts": [], "unresolved": [],
              "instrument_scores": [], "treatment_response_text": [], "family_history": rec.get("family_history"),
              "unrepresented": []}
    # --- features ---
    feats, seen = {}, {}
    for s in rec.get("surveys") or []:
        for sc in s.get("scores") or []:
            extras["instrument_scores"].append({"instrument": s.get("instrument"), "version": s.get("version"), **sc})
        for a in s.get("answers") or []:
            if a.get("value") == "unknown":
                extras["unknown_answers"].append({"instrument": s.get("instrument"), "question_id": a.get("question_id"), "label": a.get("label")}); continue
            cands = []
            if a.get("hpo_id") and a.get("value") in ("present", "absent"):
                cands.append((a["hpo_id"], a["hpo_label"], a["value"] == "absent", a.get("onset_hpo"), a.get("label")))
            for t in a.get("free_text_terms") or []:
                cands.append((t["hpo_id"], t["hpo_label"], False, None, t["text"]))
            if a.get("value") is not None and not a.get("hpo_id") and not a.get("free_text"):
                extras["unresolved"].append({"instrument": s.get("instrument"), "question_id": a.get("question_id"), "label": a.get("label"), "value": a.get("value")})
            for hid, lab, excl, ons, desc in cands:
                if hid in seen and seen[hid] != excl:
                    extras["conflicts"].append({"hpo_id": hid, "kept": "present", "dropped": "absent"})
                    if excl: continue
                seen[hid] = excl
                pf = pp.PhenotypicFeature(type=oc(hid, lab), excluded=excl, description=desc or "")
                if ons: pf.onset.CopyFrom(onset_te(ons, hp))
                feats[hid] = pf; used.add("HP")
                if ons: used.add("HP")
    # --- diseases and interpretation ---
    diseases, interps = [], []
    for d in rec.get("diseases") or []:
        if not d.get("mondo_id"):
            extras["unresolved"].append({"disease": d.get("label"), "source_code": d.get("source_code")}); continue
        used.add("MONDO")
        dz = pp.Disease(term=oc(d["mondo_id"], d.get("mondo_label")))
        if d.get("onset_hpo"): dz.onset.CopyFrom(onset_te(d["onset_hpo"], hp)); used.add("HP")
        diseases.append(dz)
        if d.get("genetic_confirmation") == "present" and d.get("hgnc_id"):
            used.add("HGNC")
            gd = pp.GeneDescriptor(value_id=d["hgnc_id"], symbol=d.get("gene_symbol", ""))
            gi = pp.GenomicInterpretation(subject_or_biosample_id=rid, interpretation_status=pp.GenomicInterpretation.CAUSATIVE)
            if d.get("variant_text"):
                gi.variant_interpretation.CopyFrom(pp.VariantInterpretation(variation_descriptor=pp.VariationDescriptor(
                    id=f"{rid}-var1", description=d["variant_text"], gene_context=gd)))
            else:
                gi.gene.CopyFrom(gd)
            interps.append(pp.Interpretation(id=f"{rid}-dx", progress_status=pp.Interpretation.SOLVED,
                                             diagnosis=pp.Diagnosis(disease=oc(d["mondo_id"], d.get("mondo_label")), genomic_interpretations=[gi])))
        elif d.get("status") == "confirmed" or d.get("genetic_confirmation") == "present":
            extras["unrepresented"].append({"what": "genetic confirmation without a resolvable gene", "disease": d.get("label")})
    # --- medications ---
    actions = []
    for m in rec.get("medications") or []:
        if m.get("response_text"):
            extras["treatment_response_text"].append({"medication": m.get("name_text"), "response": m["response_text"]})
        if not m.get("rxcui"):
            extras["unresolved"].append({"medication": m.get("name_text")}); continue
        used.add("RxNorm")
        actions.append(pp.MedicalAction(treatment=pp.Treatment(agent=oc(f"RxNorm:{m['rxcui']}", m.get("rxnorm_label")))))
    # --- files ---
    files = [pp.File(uri=f"file://{d['file_name']}", individual_to_file_identifiers={rid: rid},
                     file_attributes={"documentType": d.get("document_type") or ""}) for d in rec.get("documents") or [] if d.get("file_name")]
    # --- subject and metadata ---
    subj = pp.Individual(id=rid, alternate_ids=[f"{registry}:{rid}"], sex=SEX.get(rec.get("sex"), pp.Sex.UNKNOWN_SEX))
    if rec.get("age_at_survey") is not None:
        subj.time_at_last_encounter.CopyFrom(pp.TimeElement(age=pp.Age(iso8601duration=f"P{int(rec['age_at_survey'])}Y")))
    now = Timestamp(); now.FromDatetime(datetime.now(timezone.utc))
    md = pp.MetaData(created=now, created_by=created_by, submitted_by=registry, phenopacket_schema_version="2.0",
                     resources=[pp.Resource(version=versions.get(p, "unversioned-subset"), **RESOURCES[p]) for p in sorted(used)],
                     external_references=[pp.ExternalReference(id=f"{registry}:{rid}", description="registry participant record")])
    ppk = pp.Phenopacket(id=f"{registry}-{rid}", subject=subj, phenotypic_features=list(feats.values()), diseases=diseases,
                         interpretations=interps, medical_actions=actions, files=files, meta_data=md)
    fh = rec.get("family_history") or {}
    if fh.get("affected_relatives") == "present" or fh.get("relatives"):
        extras["unrepresented"].append({"what": "family history; a Family message with pedigree is needed", "relatives": fh.get("relatives")})
    if rec.get("respondent"):
        extras["unrepresented"].append({"what": "respondent attribution; phenopacket Evidence with an ECO term is the route", "respondent": rec["respondent"]})
    if extras["instrument_scores"]:
        extras["unrepresented"].append({"what": "instrument scores; need a coded assay (LOINC) to become Measurements"})
    if extras["treatment_response_text"]:
        extras["unrepresented"].append({"what": "treatment response text; MedicalAction.response_to_treatment needs an ontology class"})
    return ppk, extras


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resolved", type=Path, required=True)
    ap.add_argument("--assets", type=Path, required=True)
    ap.add_argument("--vocab", type=Path, help="release tables and versions.yml from bin/build_vocab.py; defaults to --assets")
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--created-by", default="rddc-registry-to-phenopacket 0.2.0")
    a = ap.parse_args()
    vocab = a.vocab or a.assets
    with open(vocab / "hp_terms.tsv", newline="") as f:
        hp = {r["id"]: r for r in csv.DictReader(f, delimiter="\t")}
    versions = {"HP": "unversioned", "MONDO": "unversioned", "HGNC": "unversioned", "RxNorm": "lexicon-only"}
    if (vocab / "versions.yml").exists():
        v = yaml.safe_load((vocab / "versions.yml").read_text()) or {}
        versions.update({k: str(v[k]) for k in versions if v.get(k)})
        if v.get("subset"): versions = {k: f"{val} (subset)" for k, val in versions.items()}
    (a.outdir / "phenopackets").mkdir(parents=True, exist_ok=True)
    (a.outdir / "extras").mkdir(parents=True, exist_ok=True)
    rows = []
    for line in a.resolved.read_text().splitlines():
        if not line.strip(): continue
        rec = json.loads(line)
        ppk, extras = build(rec, hp, versions, a.created_by)
        (a.outdir / "phenopackets" / f"{rec['id']}.phenopacket.json").write_text(MessageToJson(ppk, indent=1))
        (a.outdir / "extras" / f"{rec['id']}.extras.json").write_text(json.dumps(extras, indent=1))
        rows.append({"registry": rec["registry"], "id": rec["id"],
                     "features_present": sum(1 for f in ppk.phenotypic_features if not f.excluded),
                     "features_excluded": sum(1 for f in ppk.phenotypic_features if f.excluded),
                     "diseases": len(ppk.diseases), "interpretations": len(ppk.interpretations),
                     "medical_actions": len(ppk.medical_actions), "files": len(ppk.files),
                     "unknown_answers": len(extras["unknown_answers"]), "unresolved": len(extras["unresolved"]),
                     "unrepresented": len(extras["unrepresented"])})
    with open(a.outdir / "build_report.tsv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n"); w.writeheader(); w.writerows(rows)
    print(f"built {len(rows)} phenopackets in {a.outdir}")


if __name__ == "__main__":
    main()
