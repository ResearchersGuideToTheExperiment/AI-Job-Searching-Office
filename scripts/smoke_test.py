"""Explicit live local-model test; uses a temporary DB, never adds demo jobs to your database."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office.config import ROOT, load_settings
from office.db import Database
from office.ollama import OllamaClient
from office.service import analyze_job

settings = load_settings()
print(OllamaClient(settings).test_connection(), flush=True)
with tempfile.TemporaryDirectory() as directory:
    db = Database(Path(directory) / 'smoke.db')
    job_id = db.add_job((ROOT / 'samples/university_research.txt').read_text('utf-8'))
    result = analyze_job(db, job_id, settings)
    print(result.model_dump_json(indent=2), flush=True)
    assert result.title.value and 'Research Associate' in result.title.value
    assert result.institution.value and 'Example University' in result.institution.value
    assert result.salary.value is None, 'Salary was fabricated'
    assert result.application_email.value is None, 'Email was fabricated'
    assert result.application_url.value == 'https://careers.example.org/jobs/RA-2026'
    assert any(r.category == 'document' and '500' in r.text for r in result.requirements)
    assert any(r.importance == 'preferred' and 'Python' in r.text for r in result.requirements)
    assert sum(r.category == 'question' for r in result.requirements) >= 2
    assert not json.loads(db.job(job_id)['warnings']), 'Some outputs failed evidence validation'
    tasks = db.tasks(job_id)
    db.set_complete(tasks[0]['id'], True)
    assert Database(db.path).tasks(job_id)[0]['complete'] == 1
    print('PASS: live extraction, missing fields, evidence, database and checklist persistence.', flush=True)
