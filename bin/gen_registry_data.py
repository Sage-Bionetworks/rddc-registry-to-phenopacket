#!/usr/bin/env python3
"""Generate synthetic registry exports for two fictional registries, plus ground truth.

Two shapes are produced from the same participant pool:
  nordlike/export.json      hierarchical JSON, checklist items carry HPO codes inline
  redcaplike/Row.csv        one wide row per participant, coded answers, no ontology
  redcaplike/dictionary.csv data dictionary for the wide file (with curated rddc_target)
  truth.jsonl               what each phenopacket must contain, for the round-trip check

Values are invented. Diseases, HPO terms, genes and drugs come from assets/ so every
code in the fixtures exists; a few deliberately unmappable or obsolete values are
planted to exercise the unmapped report (see PLANTED below).
"""
import argparse, csv, json, random, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crosswalk import Vocab  # noqa: E402  the truth uses the same resolver as the pipeline

ONSET_JSON = ["before birth", "at birth", "under 1 year", "1-5 years", "5-15 years"]
ONSET_CSV = {"1": "Before birth", "2": "At birth", "3": "Under 1 year", "4": "1-5 years", "5": "5-15 years", "6": "Over 15 years"}
ONSET_CSV_TO_BAND = {"1": "before birth", "2": "at birth", "3": "under 1 year", "4": "1-5 years", "5": "5-15 years", "6": "over 15 years"}
SEIZURE_ONSET_CSV = {"1": "under 1 year", "2": "1-2 years", "3": "2-5 years", "4": "over 5 years"}

# Checklists. Each registry asks the same clinical questions with its own ids/labels.
FORMS = {
    "neuro": ("1.4", [
        ("neuro_seizures", "Has had seizures", "HP:0001250"),
        ("neuro_hypotonia", "Low muscle tone (floppy)", "HP:0001252"),
        ("neuro_dd", "Developmental delay", "HP:0001263"),
        ("neuro_speech", "Delayed speech", "HP:0000750"),
        ("neuro_microceph", "Small head size", "HP:0000252"),
        ("neuro_regression", "Lost skills previously gained", "HP:0002376"),
        ("neuro_unsteady", "Unsteady walking", "HP:0002317"),
    ]),
    "gi": ("1.1", [
        ("gi_reflux", "Reflux", "HP:0002020"),
        ("gi_constipation", "Constipation", "HP:0002019"),
        ("gi_feeding", "Feeding difficulties", "HP:0011968"),
        ("gi_ftt", "Poor weight gain", "HP:0001508"),
    ]),
    "beh": ("1.0", [
        ("beh_sleep", "Sleep problems", "HP:0002360"),
        ("beh_autism", "Autism diagnosis", "HP:0000717"),
        ("beh_hyperactive", "Hyperactivity", "HP:0000752"),
        ("beh_anxiety", "Anxiety", "HP:0000739"),
        ("beh_aggression", "Aggressive behaviour", "HP:0000718"),
    ]),
    "growth": ("1.0", [
        ("growth_short", "Short for age", "HP:0004322"),
        ("growth_hearing", "Hearing loss", "HP:0000365"),
        ("growth_scoliosis", "Curved spine (scoliosis)", "HP:0002650"),
    ]),
}
CHECKLIST_HPO = {h for _, items in FORMS.values() for _, _, h in items}

# Free-text "other" phrases. Which ones resolve is decided by the committed vocabulary subset
# (lay lexicon, release labels and synonyms) through the pipeline's own resolver, so the
# truth follows the release: "toe walking" is unmapped while HP:0040083 has no live
# replacement in the subset, and mapped once a release supplies one.
FREE_TEXT_PHRASES = [
    "hand flapping when excited", "drools a lot", "frequent ear infections", "grinds teeth at night",
    "sensitive to loud noise", "toe walking", "head banging", "very picky eater",
]
MEDS = [  # (as typed, rxcui) ; None = not in lexicon
    ("Keppra 250 twice a day", "114477"), ("levetiracetam", "114477"), ("valproate", "11118"),
    ("Onfi", "21241"), ("melatonin 3mg", "6711"), ("omeprazole", "7646"), ("Ritalin", "6901"),
    ("risperidone 0.5", "35636"), ("Topamax", "38404"), ("fish oil", None), ("CBD oil", None),
]
RESPONSES = ["fewer seizures", "no change", "helped sleep", "stopped due to behaviour", "too early to say"]
COUNTRIES = ["US", "US", "US", "CA", "GB", "AU", "DE", "BR"]
PLANTED = {"obsolete_inline_hpo": "HP:0040083"}


def load_diseases(assets):
    with open(assets / "diseases.tsv", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def make_participants(n, rng, diseases, vocab):
    free_text = [(t, vocab.resolve_phrase(t)) for t in FREE_TEXT_PHRASES]
    planted_replacement = vocab.replacement(PLANTED["obsolete_inline_hpo"])
    out = []
    for i in range(n):
        d = rng.choice(diseases)
        # A registry captures only what its checklists ask: disease-typical features
        # outside the checklists never appear, which is itself a property of registry data.
        pool = [h for h in d["hpo_pool"].split(";") if h in CHECKLIST_HPO]
        present = set(rng.sample(pool, k=min(len(pool), rng.randint(2, 4))))
        present.update(rng.sample(sorted(CHECKLIST_HPO - present), k=rng.randint(0, 1)))
        absent = set(rng.sample(sorted(CHECKLIST_HPO - present), k=rng.randint(2, 5)))
        unknown = set(rng.sample(sorted(CHECKLIST_HPO - present - absent), k=rng.randint(0, 2)))
        sex = rng.choice(["female", "male"])
        birth_year = rng.randint(2006, 2022)
        age = 2025 - birth_year
        free = rng.sample(free_text, k=rng.choice([0, 1, 1, 2]))
        meds = rng.sample(MEDS, k=rng.choice([0, 1, 1, 2, 3]))
        genetic = rng.random() < 0.8
        seizure_onset = rng.choice(list(SEIZURE_ONSET_CSV)) if "HP:0001250" in present else None
        out.append(dict(
            idx=i, disease=d, present=sorted(present), absent=sorted(absent), unknown=sorted(unknown),
            sex=sex, birth_year=birth_year, age=age, country=rng.choice(COUNTRIES),
            respondent=rng.choice(["parent", "parent", "parent", "self", "caregiver"]),
            dx_year=rng.randint(birth_year, 2025), genetic=genetic,
            onset=rng.choice(list(ONSET_CSV)), seizure_onset=seizure_onset,
            free=free, meds=[(t, r, rng.choice(RESPONSES), rng.randint(birth_year, 2025), rng.random() < 0.7) for t, r in meds],
            fh=rng.choice(["no", "no", "no", "yes", "unsure"]),
            score=round(rng.uniform(35, 90), 1),
            has_report=rng.random() < 0.5,
            planted=(i % 9 == 0), planted_replacement=planted_replacement,
        ))
    return out


def answers_for(p, hp_label):
    for form, (ver, items) in FORMS.items():
        for qid, label, hpo in items:
            if hpo in p["present"]: v = "yes"
            elif hpo in p["absent"]: v = "no"
            elif hpo in p["unknown"]: v = "unsure"
            else: v = None
            yield form, ver, qid, label, hpo, v


def write_nordlike(parts, outdir, rng):
    participants = []
    for p in parts:
        pid = f"NL-{p['idx']:04d}"
        d = p["disease"]
        surveys = []
        for form, (ver, items) in FORMS.items():
            its = []
            for f2, v2, qid, label, hpo, v in answers_for(p, None):
                if f2 != form or v is None: continue
                it = {"id": qid, "label": label, "value": v, "hpo": hpo}
                if hpo == "HP:0001250" and v == "yes" and p["seizure_onset"]:
                    it["onset"] = SEIZURE_ONSET_CSV[p["seizure_onset"]]
                its.append(it)
            if form == "neuro":
                for text, _ in p["free"]:
                    its.append({"id": "neuro_other", "label": "Other neurological or behavioural symptoms", "value": text})
            if its:
                surveys.append({"instrument": f"Symptoms - {form}", "version": ver, "language": "en",
                                "completed": f"2024-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}", "items": its})
        # planted: an obsolete inline HPO code on a few participants
        if p["idx"] % 9 == 0:
            surveys[0]["items"].append({"id": "neuro_toewalk", "label": "Walks on toes", "value": "yes", "hpo": PLANTED["obsolete_inline_hpo"]})
        surveys.append({"instrument": "PedsQL 4.0 Parent Report", "version": "4.0", "language": "en",
                        "completed": "2024-06-01", "items": [], "scores": [{"name": "total", "value": p["score"]}]})
        diag = {"label": d["label"], "year": p["dx_year"], "genetic_confirmation": "yes" if p["genetic"] else "no",
                "onset": ONSET_CSV_TO_BAND[p["onset"]]}
        if d["orphanet"]: diag["orphacode"] = d["orphanet"].replace("Orphanet:", "ORPHA:")
        if d["omim"]: diag["omim"] = d["omim"]
        if p["genetic"]:
            diag["gene"] = d["gene_symbol"]; diag["variant_text"] = f"{d['gene_symbol']} c.{rng.randint(100,3000)}{rng.choice(['C>T','del','dup','G>A'])} (de novo)"
        fam = {"affected_relatives": p["fh"], "notes": ""}
        if p["fh"] == "yes":
            fam["notes"] = "mother has mild learning difficulties"
            fam["relatives"] = [{"relation": "mother", "diagnosis": d["label"], "orphacode": diag.get("orphacode")}]
        participants.append({
            "participant_id": pid,
            "study": {"sponsor": f"{d['label']} Foundation", "protocol_version": "2.3"},
            "respondent": p["respondent"],
            "demographics": {"sex": p["sex"], "birth_year": p["birth_year"], "country": p["country"], "age_at_survey": p["age"]},
            "diagnosis": [diag], "surveys": surveys,
            "medications": [{"name_text": t, "start": str(y), "ongoing": og, "response": r} for t, _, r, y, og in p["meds"]],
            "family_history": fam,
            "uploads": [{"type": "genetic_report", "file": f"{pid}_genereport.pdf", "uploaded": "2023-11-10"}] if p["has_report"] else [],
        })
    (outdir / "nordlike").mkdir(parents=True, exist_ok=True)
    with open(outdir / "nordlike" / "export.json", "w") as f:
        json.dump({"registry": "nordlike", "export_date": "2025-10-01", "participants": participants}, f, indent=1)
    return {p["idx"]: f"NL-{p['idx']:04d}" for p in parts}


def dictionary_rows():
    yn = "1, Yes | 0, No | 9, Unsure"
    rows = [
        ("record_id", "enrol", "1.0", "text", "Record ID", "", "record.id"),
        ("resp_rel", "enrol", "1.0", "radio", "Who is completing this survey?", "1, Self | 2, Parent | 3, Other caregiver", "record.respondent"),
        ("sex", "enrol", "1.0", "radio", "Sex at birth", "1, Male | 2, Female | 3, Other", "record.sex"),
        ("birth_yr", "enrol", "1.0", "integer", "Year of birth", "", "record.birth_year"),
        ("country", "enrol", "1.0", "text", "Country of residence", "", "record.country"),
        ("dx_label", "diagnosis", "1.0", "text", "Diagnosis", "", "disease.label"),
        ("dx_orpha", "diagnosis", "1.0", "text", "ORPHAcode", "", "disease.source_code"),
        ("dx_year", "diagnosis", "1.0", "integer", "Year of diagnosis", "", "disease.diagnosis_year"),
        ("dx_genetic", "diagnosis", "1.0", "yesno", "Genetically confirmed", yn, "disease.genetic_confirmation"),
        ("gene", "diagnosis", "1.0", "text", "Gene", "", "disease.gene_symbol"),
        ("variant_text", "diagnosis", "1.0", "text", "Variant as written on the report", "", "disease.variant_text"),
        ("onset_band", "diagnosis", "1.0", "dropdown", "Age at first symptoms", " | ".join(f"{k}, {v}" for k, v in ONSET_CSV.items()), "disease.onset_text"),
    ]
    for form, (ver, items) in FORMS.items():
        for qid, label, _ in items:
            rows.append((qid, form, ver, "yesno", label, yn, "answer"))
            if qid == "neuro_seizures":
                rows.append(("neuro_seizures_onset", form, ver, "dropdown", "Age when seizures started",
                             "1, Under 1 year | 2, 1-2 years | 3, 2-5 years | 4, Over 5 years", "answer_onset:neuro_seizures"))
        rows.append((f"{form}_other", form, ver, "notes", f"Other {form} symptoms", "", "answer_text"))
    for i in (1, 2, 3):
        rows += [(f"med{i}_name", "meds", "1.0", "text", f"Medication {i} name", "", f"med[{i}].name_text"),
                 (f"med{i}_start", "meds", "1.0", "text", f"Medication {i} start year", "", f"med[{i}].start_text"),
                 (f"med{i}_ongoing", "meds", "1.0", "yesno", f"Medication {i} still taking", "1, Yes | 0, No", f"med[{i}].ongoing"),
                 (f"med{i}_effect", "meds", "1.0", "notes", f"Medication {i} effect", "", f"med[{i}].response_text")]
    rows += [("fh_affected", "family", "1.0", "yesno", "Any relatives with a similar condition", yn, "family.affected_relatives"),
             ("fh_notes", "family", "1.0", "notes", "Family history details", "", "family.notes"),
             ("pedsql_total", "pedsql", "4.0", "decimal", "PedsQL total score", "", "score:total"),
             ("report_file", "uploads", "1.0", "file", "Genetic report upload", "", "document:genetic_report")]
    return rows


def write_redcaplike(parts, outdir):
    rows = dictionary_rows()
    fields = [r[0] for r in rows]
    (outdir / "redcaplike").mkdir(parents=True, exist_ok=True)
    with open(outdir / "redcaplike" / "dictionary.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["field", "form", "form_version", "type", "label", "choices", "rddc_target"]); w.writerows(rows)
    ids = {}
    with open(outdir / "redcaplike" / "Row.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for p in parts:
            pid = f"RC{p['idx']:05d}"; ids[p["idx"]] = pid
            d = p["disease"]
            r = {k: "" for k in fields}
            r.update(record_id=pid, resp_rel={"self": "1", "parent": "2", "caregiver": "3"}[p["respondent"]],
                     sex={"male": "1", "female": "2"}[p["sex"]], birth_yr=p["birth_year"], country=p["country"],
                     dx_label=d["label"], dx_orpha=d["orphanet"].replace("Orphanet:", "ORPHA:") if d["orphanet"] else "",
                     dx_year=p["dx_year"], dx_genetic="1" if p["genetic"] else "0",
                     gene=d["gene_symbol"] if p["genetic"] else "", onset_band=p["onset"])
            if p["genetic"]: r["variant_text"] = f"{d['gene_symbol']} p.(?) see report"
            for form, ver, qid, label, hpo, v in answers_for(p, None):
                if v is not None: r[qid] = {"yes": "1", "no": "0", "unsure": "9"}[v]
            if p["seizure_onset"] and "HP:0001250" in p["present"]: r["neuro_seizures_onset"] = p["seizure_onset"]
            if p["free"]: r["neuro_other"] = "; ".join(t for t, _ in p["free"])
            for i, (t, _, resp, y, og) in enumerate(p["meds"][:3], start=1):
                r[f"med{i}_name"] = t; r[f"med{i}_start"] = y; r[f"med{i}_ongoing"] = "1" if og else "0"; r[f"med{i}_effect"] = resp
            r["fh_affected"] = {"yes": "1", "no": "0", "unsure": "9"}[p["fh"]]
            if p["fh"] == "yes": r["fh_notes"] = "mother has mild learning difficulties"
            r["pedsql_total"] = p["score"]
            if p["has_report"]: r["report_file"] = f"{pid}_report.pdf"
            w.writerow(r)
    return ids


def write_truth(parts, nl_ids, rc_ids, outdir):
    with open(outdir / "truth.jsonl", "w") as f:
        for p in parts:
            d = p["disease"]
            free_hpo = sorted({h for _, h in p["free"] if h})
            unmapped_free = sorted(t for t, h in p["free"] if not h)
            meds = sorted({r for _, r, *_ in p["meds"] if r})
            unmapped_meds = sorted(t for t, r, *_ in p["meds"] if not r)
            present = set(p["present"]) | set(free_hpo)
            base = dict(mondo=d["mondo_id"], hgnc=d["hgnc_id"] if p["genetic"] else None,
                        present=sorted(present), absent=p["absent"],
                        rxcui=meds, unmapped_free_text=unmapped_free, unmapped_medications=unmapped_meds)
            # only the JSON registry carries the planted obsolete code; its live replacement is expected there
            nl_present = sorted(present | ({p["planted_replacement"]} if p["planted"] and p["planted_replacement"] else set()))
            f.write(json.dumps({"registry": "nordlike", "id": nl_ids[p["idx"]], **base, "present": nl_present,
                                "planted_obsolete": PLANTED["obsolete_inline_hpo"] if p["planted"] else None,
                                "planted_replacement": p["planted_replacement"] if p["planted"] else None}) + "\n")
            f.write(json.dumps({"registry": "redcaplike", "id": rc_ids[p["idx"]], **base,
                                "rxcui": sorted({r for _, r, *_ in p["meds"][:3] if r}),
                                "unmapped_medications": sorted(t for t, r, *_ in p["meds"][:3] if not r)}) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--assets", type=Path, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("-n", type=int, default=24)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    parts = make_participants(a.n, rng, load_diseases(a.assets), Vocab(a.assets, "nordlike"))
    nl = write_nordlike(parts, a.outdir, rng)
    rc = write_redcaplike(parts, a.outdir)
    write_truth(parts, nl, rc, a.outdir)
    print(f"wrote {len(parts)} participants x 2 registries to {a.outdir}")


if __name__ == "__main__":
    main()
