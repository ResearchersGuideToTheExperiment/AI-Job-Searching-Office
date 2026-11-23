import json
from office.db import Database
from office.local_files import sync_local_files
from office.career import extract_career, CareerExtraction, CareerFact
from office.config import Settings
from office.ollama import OllamaClient
from test_profile import synthetic_cv


def test_local_sync_preserves_edits_and_deduplicates(tmp_path):
    root = tmp_path
    instructions = root / 'PUT_YOUR_AI_MODEL_HERE/AI_instructions'
    instructions.mkdir(parents=True)
    (root / 'PUT_YOURCV_HERE').mkdir()
    (instructions / 'writing_style.md').write_text('s' * 2501, encoding='utf-8')
    (instructions / 'job_preferences.md').write_text('p' * 3501, encoding='utf-8')
    (root / 'PUT_YOURCV_HERE/master.docx').write_bytes(synthetic_cv())
    db = Database(root / 'data/office.sqlite3')
    assert len(sync_local_files(db)) == 3
    assert len(db.preferences()['style']) == 2501
    assert len(db.preferences()['preferences']) == 3501
    assert len(db.profile_documents()) == 1
    db.save_preferences('Dashboard edit', 'Other edit')
    assert sync_local_files(db) == []
    assert db.preferences()['style'] == 'Dashboard edit'
    (instructions / 'writing_style.md').write_text('Updated file', encoding='utf-8')
    sync_local_files(db)
    assert db.preferences()['style'] == 'Updated file'
    assert db.preferences()['preferences'] == 'Other edit'
    assert len(db.profile_documents()) == 1


def test_unsupported_fact_does_not_abort_valid_extraction(tmp_path, monkeypatch):
    db = Database(tmp_path / 'db')
    original = 'Designed visual perception experiments. PhD in Psychology.'
    doc = db.add_profile_document('cv.txt', original.encode(), original, 'master_cv')
    monkeypatch.setattr(OllamaClient, 'structured', lambda *args: CareerExtraction(facts=[
        CareerFact(category='research', text='Expert researcher', source_quote='Designed visual perception experiments.'),
        CareerFact(category='education', text='PhD in Psychology.', source_quote='PhD in Psychology.'),
        CareerFact(category='publications', text='50 papers', source_quote='50 papers')]))
    facts = extract_career(db, doc, Settings())
    assert len(facts) == 2
    assert facts[0]['text'] == 'Designed visual perception experiments.'
    assert not db.facts(True)
    assert db.operations()[0]['state'] == 'needs_review'
    assert len(json.loads(db.operations()[0]['detail'])['issues']) == 2
