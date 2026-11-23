import pytest
from office.db import Database
from office.config import Settings
from office.models import Analysis, Fact, Requirement, FACT_FIELDS
from office.evaluation import evaluate_job, analysis_fingerprint, evaluation_current, CompactDecision, Evidence
from office.ollama import OllamaClient


def prepared_job(db):
    job = db.add_job('Experience with participant testing is required. Python is desirable.')
    analysis = Analysis(**{k: Fact(value=None, source_quote=None) for k in FACT_FIELDS}, requirements=[
        Requirement(category='essential', text='Experience with participant testing is required.', source_quote='Experience with participant testing is required.', importance='mandatory'),
        Requirement(category='desirable', text='Python is desirable.', source_quote='Python is desirable.', importance='preferred')])
    run = db.start_run(job, Settings(), 'test')
    db.save_analysis(job, analysis, [], [], run, '{}')
    db.review_analysis(job, analysis_fingerprint(analysis))
    return job


def test_scoring_evidence_and_staleness(tmp_path, monkeypatch):
    db = Database(tmp_path / 'db')
    job = prepared_job(db)
    fact = db.save_fact(None, 'research', 'Tested 40 participants in visual perception experiments.', True)
    db.save_fact(None, 'skills', 'Python', False)
    def answer(self, schema, prompt, data, **kwargs):
        assert len(data['confirmed_facts']) == 1
        if data['criterion']['category'] == 'essential':
            return CompactDecision(result='satisfied', explanation='Direct participant-testing evidence.', fact_ids=[fact], eligibility_concern=None)
        return CompactDecision(result='unknown', explanation='No verified Python evidence.', fact_ids=[], eligibility_concern=None)
    monkeypatch.setattr(OllamaClient, 'structured', answer)
    result = evaluate_job(db, job, Settings())
    assert result['score'] == 67
    assert result['unknown_count'] == 1
    assert evaluation_current(db, job, db.evaluation(job))
    db.save_fact(fact, 'research', 'Tested 41 participants.', True)
    assert not evaluation_current(db, job, db.evaluation(job))


def test_invalid_evidence_is_unknown(tmp_path, monkeypatch):
    db = Database(tmp_path / 'db')
    job = prepared_job(db)
    db.save_fact(None, 'research', 'Participant testing', True)
    monkeypatch.setattr(OllamaClient, 'structured', lambda *args, **kwargs: CompactDecision(result='satisfied', explanation='Invented', fact_ids=[999], eligibility_concern=None))
    result = evaluate_job(db, job, Settings())
    assert result['score'] == 0
    assert result['unknown_count'] == 2
