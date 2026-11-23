"""Deterministic synthetic workflow; no network, no real personal data, no submission."""
import json
from pathlib import Path
from docx import Document
from office.db import Database
from office.config import Settings
from office.retrieval import Page, import_url
from office.career import upload_career, extract_career, CareerExtraction, CareerFact
from office.models import Analysis, Fact, Requirement, FACT_FIELDS
from office.service import analyze_job
from office.ollama import OllamaClient
from office.evaluation import CompactDecision, evaluate_job, analysis_fingerprint
from office.documents import DraftPlan, FactSelection, prepare_package, generate_document
from test_profile import synthetic_cv


def test_full_synthetic_workflow(tmp_path, monkeypatch):
    db = Database(tmp_path / 'office.db')
    html = (Path(__file__).resolve().parents[1] / 'samples/research_job.html').read_bytes()
    class Fixture:
        def fetch(self, url):
            return Page(url, html, 'text/html')
    job, warnings = import_url(db, 'https://university.example/job', Fixture())
    assert not warnings and db.sources(job)[0]['content'] == html
    cv = synthetic_cv()
    doc_id = upload_career(db, 'master.docx', cv, 'master_cv')
    fact_text = 'Designed virtual reality experiments on visual perception and tested 40 participants.'
    def structured(self, schema, prompt, data, **kwargs):
        if schema is CareerExtraction:
            return CareerExtraction(facts=[CareerFact(category='research', text=fact_text, source_quote=fact_text)])
        if schema is CompactDecision:
            return CompactDecision(result='satisfied', explanation='Visual perception and participant-testing evidence meets the criterion.', fact_ids=[db.facts(True)[0]['id']], eligibility_concern=None)
        if schema is DraftPlan:
            return DraftPlan(paragraphs=[FactSelection(fact_ids=[db.facts(True)[0]['id']])], missing_information=[])
        raise AssertionError(schema)
    monkeypatch.setattr(OllamaClient, 'structured', structured)
    extract_career(db, doc_id, Settings())
    assert not db.facts(True)
    fact = db.facts()[0]
    db.save_fact(fact['id'], fact['category'], fact['text'], True)
    analysis = Analysis(**{f: Fact(value=None, source_quote=None) for f in FACT_FIELDS}, requirements=[])
    for category, text in [('essential','Experience designing visual perception experiments and testing participants is essential.'), ('document','Upload a tailored CV.'), ('document','Upload a motivation letter of no more than 300 words.'), ('question','Answer question 1: Describe your research methodology experience (maximum 150 words).')]:
        analysis.requirements.append(Requirement(category=category, text=text, source_quote=text, importance='mandatory'))
    analysis.application_url = Fact(value='https://careers.example.org/apply/visual-perception', source_quote='https://careers.example.org/apply/visual-perception')
    monkeypatch.setattr(OllamaClient, 'extract', lambda *args: (analysis, analysis.model_dump_json()))
    result = analyze_job(db, job, Settings())
    db.review_analysis(job, analysis_fingerprint(result))
    evaluation = evaluate_job(db, job, Settings())
    assert evaluation['score'] == 100
    from office.decisions import save_decision
    save_decision(db,job,db.evaluation(job)['id'],100,'approved')
    prepare_package(db, job)
    plan = json.loads(db.package(job)['plan'])
    for item in plan:
        path = generate_document(db, job, item['key'], Settings())
        assert path.is_file()
        assert '40 participants' in '\n'.join(p.text for p in Document(path).paragraphs)
    assert len(db.drafts(db.package(job)['id'])) == 3
    tasks = db.tasks(job)
    assert any('https://careers.example.org/apply/visual-perception' in t['text'] for t in tasks)
    db.set_complete(tasks[0]['id'], True)
    assert Database(db.path).tasks(job)[0]['complete'] == 1
    assert db.profile_document(doc_id)['content'] == cv
