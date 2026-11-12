#!/usr/bin/env python3
"""Resolve the codes and texts in RegistryRecords to ontology terms, and report what did not resolve.

Input is the LinkML-Map output: either a RegistryExport JSON ({"records": [...]}) or
JSON Lines of RegistryRecord objects. Output is the same records with resolution
fields added (hpo_id, mondo_id, hgnc_id, rxcui, onset_hpo, resolution), plus a TSV of
every value that could not be resolved and why. Nothing is dropped silently: an
unanswered checklist item is removed, everything else either resolves or is reported.

Resolution order for a checklist answer:
  1. inline source code, checked against the HPO table (obsolete codes are replaced
     when the table names a replacement, otherwise reported)
  2. survey lookup table assets/survey_lookups/<registry>_<instrument>_<version>.tsv
  3. exact match of the item label against HPO labels
Free text is split on ; , and "and", and each phrase is matched against lay_terms.tsv.
Disease codes go through MONDO cross-references, then label match.
"""
import argparse, csv, json, re
from pathlib import Path

PREFIX_FIX = {"ORPHA": "Orphanet", "ORPHANET": "Orphanet", "MIM": "OMIM"}


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())).strip()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def read_tsv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


class Vocab:
    """Release tables (hp_terms, hp_synonyms, mondo_xrefs, mondo_labels, genes) come from the
    vocab directory, built by bin/build_vocab.py; curated tables (onset bands, lay terms,
    drug lexicon, survey lookups) come from assets. The committed assets directory holds a
    subset of both, so vocab defaults to assets."""

    def __init__(self, assets, registry, vocab=None):
        vocab = vocab or assets
        self.hp = {r["id"]: r for r in read_tsv(vocab / "hp_terms.tsv")}
        self.hp_by_label = {norm(r["label"]): r["id"] for r in self.hp.values() if r["obsolete"] != "true"}
        self.hp_by_synonym = {}
        if (vocab / "hp_synonyms.tsv").exists():
            for r in read_tsv(vocab / "hp_synonyms.tsv"):
                if r["scope"] in ("exact", "related") and r["hpo_id"] in self.hp:
                    self.hp_by_synonym.setdefault(norm(r["synonym"]), r["hpo_id"])
        self.mondo_by_xref, self.mondo_by_label, self.hgnc_by_symbol = {}, {}, {}
        if (vocab / "mondo_xrefs.tsv").exists():
            for r in read_tsv(vocab / "mondo_xrefs.tsv"):
                if r["predicate"] in ("", "skos:exactMatch"):
                    self.mondo_by_xref.setdefault(r["xref"], {"mondo_id": r["mondo_id"], "label": r["mondo_label"]})
            for r in read_tsv(vocab / "mondo_labels.tsv"):
                self.mondo_by_label.setdefault(norm(r["label"]), {"mondo_id": r["mondo_id"], "label": r["label"]})
        if (vocab / "genes.tsv").exists():
            for r in sorted(read_tsv(vocab / "genes.tsv"), key=lambda r: r["kind"] != "symbol"):
                self.hgnc_by_symbol.setdefault(r["symbol"].upper(), r["hgnc_id"])
        if not self.mondo_by_xref:  # fallback: the generator's disease catalogue
            for d in read_tsv(assets / "diseases.tsv"):
                for x in (d["orphanet"], d["omim"]):
                    if x: self.mondo_by_xref[x] = d
                self.mondo_by_label[norm(d["label"])] = d
                if d["gene_symbol"]: self.hgnc_by_symbol.setdefault(d["gene_symbol"].upper(), d["hgnc_id"])
        self.onset = {norm(r["band_text"]): r for r in read_tsv(assets / "onset_bands.tsv")}
        self.lay = {norm(r["text"]): r["hpo_id"] for r in read_tsv(assets / "lay_terms.tsv")}
        self.drugs = sorted(((norm(r["text"]), r) for r in read_tsv(assets / "drug_lexicon.tsv")), key=lambda kv: -len(kv[0]))
        self.lookups = {}
        for p in (assets / "survey_lookups").glob(f"{registry}_*.tsv"):
            self.lookups[p.stem] = {r["question_id"]: r["hpo_id"] for r in read_tsv(p)}

    def hpo(self, hid):
        return self.hp.get(hid)

    def resolve_phrase(self, phrase):
        """Free-text phrase -> HPO id: lay lexicon, release label, release synonym, then a
        lexicon key contained in the phrase. None when nothing matches."""
        ph = norm(phrase)
        if not ph: return None
        return (self.lay.get(ph) or self.hp_by_label.get(ph) or self.hp_by_synonym.get(ph)
                or next((h for k, h in self.lay.items() if k in ph), None))

    def replacement(self, hid):
        """Current id for an obsolete term when the release names a live replacement."""
        t = self.hp.get(hid)
        if not t or t["obsolete"] != "true": return None
        rep = t["replaced_by"]
        return rep if rep and rep in self.hp and self.hp[rep]["obsolete"] != "true" else None

    def lookup(self, registry, instrument, version, qid):
        return self.lookups.get(f"{registry}_{slug(instrument)}_{version}", {}).get(qid)


class Crosswalk:
    def __init__(self, vocab, registry):
        self.v, self.registry, self.unmapped = vocab, registry, []

    def report(self, rid, field, value, reason):
        self.unmapped.append({"registry": self.registry, "record_id": rid, "field": field, "value": value, "reason": reason})

    def fix_prefix(self, code):
        if not code or ":" not in code: return code
        pre, _, local = code.partition(":")
        return f"{PREFIX_FIX.get(pre.upper(), pre)}:{local.strip()}"

    def resolve_hpo(self, rid, field, hid):
        t = self.v.hpo(hid)
        if not t:
            self.report(rid, field, hid, "code not in HPO table"); return None, None
        if t["obsolete"] == "true":
            rep = self.v.replacement(hid)
            if rep:
                return rep, "obsolete_replaced"
            self.report(rid, field, hid, "obsolete HPO term with no replacement"); return None, None
        return hid, "inline_code"

    def resolve_onset(self, rid, field, text):
        if not text: return None
        r = self.v.onset.get(norm(text))
        if not r:
            self.report(rid, field, text, "onset band not in onset_bands.tsv"); return None
        return r["hpo_id"]

    def disease(self, rid, d, label_key="label"):
        code = self.fix_prefix(d.get("source_code"))
        hit = self.v.mondo_by_xref.get(code) if code else None
        res = "xref" if hit else None
        if not hit and d.get(label_key):
            hit = self.v.mondo_by_label.get(norm(d[label_key])); res = "label_match" if hit else None
        if hit:
            d.update(mondo_id=hit["mondo_id"], mondo_label=hit["label"], resolution=res)
        else:
            self.report(rid, "disease" if label_key == "label" else "family_history.relative", code or d.get(label_key), "no MONDO cross-reference or label match")
            d["resolution"] = "unmapped"
        if d.get("onset_text"):
            d["onset_hpo"] = self.resolve_onset(rid, "disease.onset_text", d["onset_text"])
        if d.get("gene_symbol"):
            h = self.v.hgnc_by_symbol.get(d["gene_symbol"].upper())
            if h: d["hgnc_id"] = h
            else: self.report(rid, "disease.gene_symbol", d["gene_symbol"], "gene symbol not in HGNC table")
        return d

    def answer(self, rid, survey, a):
        if a.get("value") is None and not a.get("free_text"):
            return None  # unanswered item
        field = f"{survey.get('instrument')}/{a.get('question_id')}"
        if a.get("value") is not None:
            hid = res = None
            code_failed = False
            if a.get("source_code"):
                hid, res = self.resolve_hpo(rid, field + ".source_code", a["source_code"])
                code_failed = hid is None
            if not hid:
                lk = self.v.lookup(self.registry, survey.get("instrument"), survey.get("version"), a.get("question_id"))
                if lk: hid, res = self.resolve_hpo(rid, field + ".lookup", lk); res = res and "survey_lookup"
            if not hid and a.get("label"):
                lab = self.v.hp_by_label.get(norm(a["label"]))
                if lab: hid, res = lab, "label_match"
                else:
                    syn = self.v.hp_by_synonym.get(norm(a["label"]))
                    if syn: hid, res = syn, "synonym_match"
            if hid:
                a.update(hpo_id=hid, hpo_label=self.v.hp[hid]["label"], resolution=res)
            else:
                a["resolution"] = "unmapped"
                if not code_failed:  # the code path already reported why
                    self.report(rid, field, a.get("label"), "checklist item has no code, lookup or label match")
        if a.get("free_text"):
            terms = []
            for phrase in re.split(r"[;,]|\band\b", a["free_text"]):
                if not norm(phrase): continue
                hid = self.v.resolve_phrase(phrase)
                if hid: terms.append({"text": phrase.strip(), "hpo_id": hid, "hpo_label": self.v.hp[hid]["label"]})
                else: self.report(rid, field + ".free_text", phrase.strip(), "phrase not in lay-term lexicon")
            a["free_text_terms"] = terms
        if a.get("onset_text"):
            a["onset_hpo"] = self.resolve_onset(rid, field + ".onset_text", a["onset_text"])
        return a

    def medication(self, rid, m):
        t = norm(m.get("name_text"))
        for key, r in self.v.drugs:
            if key and key in t:
                m.update(rxcui=r["rxcui"], rxnorm_label=r["label"], resolution="lexicon"); return m
        m["resolution"] = "unmapped"
        self.report(rid, "medication.name_text", m.get("name_text"), "no drug lexicon match")
        return m

    def record(self, rec):
        rid = rec["id"]
        rec["registry"] = rec.get("registry") or self.registry
        rec["diseases"] = [self.disease(rid, d) for d in rec.get("diseases") or []]
        for s in rec.get("surveys") or []:
            s["answers"] = [x for x in (self.answer(rid, s, a) for a in s.get("answers") or []) if x]
        rec["medications"] = [self.medication(rid, m) for m in rec.get("medications") or []]
        fh = rec.get("family_history") or {}
        for r in fh.get("relatives") or []:
            self.disease(rid, r, label_key="diagnosis_label")  # relatives' diagnoses resolve the same way
        return rec


def load_records(path):
    text = Path(path).read_text()
    if path.suffix == ".jsonl":
        return [json.loads(l) for l in text.splitlines() if l.strip()]
    d = json.loads(text)
    return d["records"] if isinstance(d, dict) and "records" in d else [d]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--assets", type=Path, required=True)
    ap.add_argument("--vocab", type=Path, help="release tables from bin/build_vocab.py; defaults to --assets")
    ap.add_argument("--registry", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--unmapped", type=Path, required=True)
    a = ap.parse_args()
    xw = Crosswalk(Vocab(a.assets, a.registry, a.vocab), a.registry)
    recs = [xw.record(r) for r in load_records(a.records)]
    with open(a.out, "w") as f:
        for r in recs: f.write(json.dumps(r) + "\n")
    with open(a.unmapped, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["registry", "record_id", "field", "value", "reason"], delimiter="\t", lineterminator="\n")
        w.writeheader(); w.writerows(xw.unmapped)
    counts = {}
    for u in xw.unmapped: counts[u["reason"]] = counts.get(u["reason"], 0) + 1
    print(f"{a.registry}: {len(recs)} records, {len(xw.unmapped)} unmapped values")
    for k, v in sorted(counts.items()): print(f"  {v:4d}  {k}")


if __name__ == "__main__":
    main()
