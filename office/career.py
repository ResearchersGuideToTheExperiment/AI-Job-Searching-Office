import json
import hashlib
from typing import Literal
from pydantic import Field
from office.models import StrictModel, normalize
from office.chunks import split_text
from office.ollama import OllamaClient
from office.ingest import read_upload

CATEGORIES = ('identity', 'education', 'certificates', 'work_history', 'experience', 'research', 'skills', 'publications', 'teaching', 'projects', 'languages', 'other')


class CareerFact(StrictModel):
    category: Literal['identity', 'education', 'certificates', 'work_history', 'experience', 'research', 'skills', 'publications', 'teaching', 'projects', 'languages', 'other']
    text: str = Field(min_length=1, max_length=2500)
    source_quote: str = Field(min_length=1)


class CareerExtraction(StrictModel):
    facts: list[CareerFact]


def profile_fingerprint(facts):
    return hashlib.sha256(json.dumps([(f['id'], f['category'], f['text']) for f in facts], sort_keys=True).encode()).hexdigest()


def extract_career(db, document_id, settings, progress=None):
    from office.activity import activity
    with activity(db,2,'Reading CV profile'):
        return _extract_career(db,document_id,settings,progress)


def _extract_career(db, document_id, settings, progress=None):
    document = db.profile_document(document_id)
    client = OllamaClient(settings)
    facts, seen, issues = [], set(), []
    chunks = split_text(document['text'])
    run = db.operation_start('profile extraction', settings.model)
    try:
        for index, chunk in enumerate(chunks):
            if progress:
                progress(f'Extracting career document section {index + 1}/{len(chunks)}')
            extracted = client.structured(CareerExtraction,
                'Extract every career fact explicitly stated in this document section. Always include the candidate name from the heading as an identity fact, plus any contact details. Include education, certificates, dates, work history, experience, research, skills, publications, teaching, projects and languages. Use certificates for explicitly awarded certifications or completed certificate courses. Use work_history for employment positions and experience for practical experience not better classified as research, teaching or a named project. '
                'Copy text and supporting source_quote verbatim. Do not turn future intentions or requests into experience. Do not infer qualifications. Each fact must be self-contained; include dates, roles and institutions when present. Missing categories have no facts.', {'document': chunk})
            for fact in extracted.facts:
                if normalize(fact.source_quote) not in normalize(chunk):
                    issues.append(f'Section {index + 1}: omitted an unsupported {fact.category} fact; its quote was not in the original. Review this section for missing information.')
                    continue
                if normalize(fact.text) not in normalize(fact.source_quote):
                    # Model paraphrases are not evidence. Retain the source's own
                    # words as an unconfirmed candidate instead of aborting the CV.
                    if len(fact.source_quote) > 2500:
                        issues.append(f'Section {index + 1}: omitted an oversized {fact.category} passage. Add shorter facts manually.')
                        continue
                    fact.text = fact.source_quote
                    issues.append(f'Section {index + 1}: replaced a paraphrased {fact.category} fact with its exact source quote; confirmation required.')
                key = (fact.category, normalize(fact.text))
                if key not in seen:
                    seen.add(key)
                    facts.append(fact.model_dump())
            db.save_extracted_facts(document_id, facts)
        db.operation_finish(run, 'needs_review' if issues or not facts else 'success', json.dumps({'document_id': document_id, 'facts': len(facts), 'sections': len(chunks), 'issues': issues or (['No facts extracted. Review the source and add facts manually.'] if not facts else [])}))
        return facts
    except Exception as exc:
        db.operation_finish(run, 'failed', f'{exc} Valid facts from completed sections were retained for review. ' + json.dumps(issues))
        raise


def upload_career(db, name, content, kind):
    if kind == 'master_cv' and not name.lower().endswith(('.pdf', '.docx')):
        raise ValueError('Master CV must be a PDF or DOCX.')
    with db.connect() as conn:
        existing = conn.execute('SELECT id FROM profile_documents WHERE content=? AND kind=?', (content, kind)).fetchone()
    if existing:
        return existing['id']
    text = read_upload(name, content)
    return db.add_profile_document(name, content, text, kind)
