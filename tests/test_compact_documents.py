"""Agent 3 must not repeat long facts in model output or export partial plans."""
import json

import pytest
from docx import Document
from pydantic import ValidationError

from office.career import profile_fingerprint
from office.config import Settings
from office.db import Database
from office.decisions import save_decision
from office.documents import (
    DRAFT_OUTPUT_TOKENS, DraftPlan, FactSelection, generate_document,
    prepare_package, select_draft,
)
from office.evaluation import analysis_fingerprint
from office.models import Analysis, Fact, Requirement, FACT_FIELDS
from office.ollama import OllamaClient, OllamaError


def approved_package(tmp_path, instruction, category='document'):
    db = Database(tmp_path / 'office.db')
    job = db.add_job(instruction)
    fact_text = ('Tested 40 participants. ' + 'Documented the experimental methods and analysis. ' * 40).strip()
    db.save_fact(None, 'identity', 'Example Applicant', True)
    fact_id = db.save_fact(None, 'research', fact_text, True)
    analysis = Analysis(**{key: Fact(value=None, source_quote=None) for key in FACT_FIELDS},
                        requirements=[Requirement(category=category, text=instruction,
                                                  source_quote=instruction, importance='mandatory')])
    run = db.start_run(job, Settings(), 'fixture')
    db.save_analysis(job, analysis, [], [], run, '{}')
    evaluation = db.save_evaluation(job, profile_fingerprint(db.facts(True)), analysis_fingerprint(analysis),
                                    {'score': 100, 'criteria': []})
    save_decision(db, job, evaluation, 100, 'approved')
    prepare_package(db, job)
    item = json.loads(db.package(job)['plan'])[0]
    return db, job, item, fact_id, fact_text


@pytest.mark.parametrize('instruction,category', [
    ('Upload a supporting statement.', 'document'),
    ('Describe your research methods.', 'question'),
])
@pytest.mark.parametrize('failure', ['output_limit', 'schema', None])
def test_compact_generation_exports_full_facts_and_recovers(tmp_path, monkeypatch, instruction, category, failure):
    db, job, item, fact_id, fact_text = approved_package(tmp_path, instruction, category)
    client_calls = []
    plan = DraftPlan(paragraphs=[FactSelection(fact_ids=[fact_id])], missing_information=[])
    # Exercise the real structured response parser and truncation detection.
    def request(self, method, endpoint, **kwargs):
        assert endpoint == '/api/chat'
        payload = kwargs['json']
        client_calls.append(payload)
        assert payload['options']['num_predict'] == DRAFT_OUTPUT_TOKENS
        assert 'text' not in payload['format']['$defs']['FactSelection']['properties']
        facts = json.loads(payload['messages'][1]['content'])['confirmed_facts']
        assert fact_text in [fact['text'] for fact in facts]
        assert not any(fact['category'] == 'identity' for fact in facts)
        if len(client_calls) == 1 and failure:
            return {'done_reason': 'length' if failure == 'output_limit' else 'stop',
                    'eval_count': DRAFT_OUTPUT_TOKENS if failure == 'output_limit' else 10,
                    'message': {'content': '{"paragraphs":['}}
        return {'done_reason': 'stop', 'eval_count': 35, 'message': {'content': plan.model_dump_json()}}
    monkeypatch.setattr(OllamaClient, 'test_connection', lambda self: 'ok')
    monkeypatch.setattr(OllamaClient, 'request', request)
    path = generate_document(db, job, item['key'], Settings())
    assert len(client_calls) == (2 if failure else 1)
    assert len(plan.model_dump_json()) < 100
    draft = db.drafts(db.package(job)['id'])[0]
    assert draft['body'] == 'I ' + fact_text[0].lower() + fact_text[1:].strip()
    assert json.loads(draft['evidence']) == [{'fact_id': fact_id, 'quote': fact_text}]
    assert draft['body'] in '\n'.join(p.text for p in Document(path).paragraphs)


@pytest.mark.parametrize('failure', ['output_limit', 'schema', 'unknown_id', 'connection'])
def test_generation_failure_is_bounded_and_exports_nothing(tmp_path, monkeypatch, failure):
    db, job, item, fact_id, _ = approved_package(tmp_path, 'Upload a supporting statement.')
    calls = []
    def structured(self, schema, prompt, data, **kwargs):
        calls.append(data)
        if failure == 'unknown_id':
            return DraftPlan(paragraphs=[FactSelection(fact_ids=[fact_id + 999])], missing_information=[])
        error = OllamaError('Simulated failure')
        error.kind = failure
        raise error
    monkeypatch.setattr(OllamaClient, 'structured', structured)
    with pytest.raises(OllamaError):
        generate_document(db, job, item['key'], Settings())
    assert len(calls) == (1 if failure == 'connection' else 2)
    assert db.drafts(db.package(job)['id']) == []
    assert not list(tmp_path.rglob('*.docx'))


def test_identity_facts_are_not_accepted_as_draft_content(monkeypatch):
    monkeypatch.setattr(OllamaClient, 'structured', lambda *args, **kwargs:
                        DraftPlan(paragraphs=[FactSelection(fact_ids=[1])], missing_information=[]))
    with pytest.raises(OllamaError, match='outside the confirmed drafting context'):
        select_draft(OllamaClient(Settings()), {'confirmed_facts': [{'id': 1, 'category': 'identity', 'text': 'Name'}]})


def test_explicit_limits_still_prevent_oversized_exports(tmp_path, monkeypatch):
    db, job, item, fact_id, _ = approved_package(tmp_path, 'Describe your methods (maximum 50 words).', 'question')
    monkeypatch.setattr(OllamaClient, 'structured', lambda *args, **kwargs:
                        DraftPlan(paragraphs=[FactSelection(fact_ids=[fact_id])], missing_information=[]))
    with pytest.raises(ValueError, match='exceeds an explicit length limit'):
        generate_document(db, job, item['key'], Settings())
    assert not db.drafts(db.package(job)['id'])
    assert not list(tmp_path.rglob('*.docx'))


def test_missing_information_remains_visible(tmp_path, monkeypatch):
    db, job, item, _, _ = approved_package(tmp_path, 'Upload a supporting statement.')
    note = 'Provide a verified example of teaching experience.'
    monkeypatch.setattr(OllamaClient, 'structured', lambda *args, **kwargs:
                        DraftPlan(paragraphs=[], missing_information=[note]))
    generate_document(db, job, item['key'], Settings())
    draft = db.drafts(db.package(job)['id'])[0]
    assert note in json.loads(draft['warnings'])
    assert 'ADD VERIFIED INFORMATION' in draft['body']
    assert json.loads(draft['evidence']) == []


@pytest.mark.parametrize('payload', [
    {'paragraphs': [{'fact_ids': [1]}] * 13, 'missing_information': []},
    {'paragraphs': [{'fact_ids': list(range(7))}], 'missing_information': []},
    {'paragraphs': [], 'missing_information': ['x' * 161]},
    {'paragraphs': [], 'missing_information': ['Missing evidence.'] * 7},
])
def test_model_response_size_is_bounded_by_schema(payload):
    with pytest.raises(ValidationError):
        DraftPlan.model_validate(payload)
