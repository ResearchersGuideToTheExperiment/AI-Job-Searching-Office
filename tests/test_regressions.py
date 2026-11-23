import json
import sqlite3
from office.db import Database
from office.models import Analysis, Fact, Requirement, FACT_FIELDS
from office.documents import plan_documents
from office.config import Settings
from office.ollama import OllamaClient
from office.service import analyze_job


def test_old_database_rows_survive_extension(tmp_path):
    path = tmp_path / 'old.db'
    with sqlite3.connect(path) as conn:
        conn.executescript("""CREATE TABLE jobs (id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP, original TEXT NOT NULL, filename TEXT, original_file BLOB, source_url TEXT, status TEXT NOT NULL DEFAULT 'New', analysis TEXT, warnings TEXT NOT NULL DEFAULT '[]');
        INSERT INTO jobs(original,status) VALUES ('existing original', 'Preparing');""")
    db = Database(path)
    assert db.job(1)['original'] == 'existing original'
    assert db.job(1)['status'] == 'Preparing'
    assert db.facts() == []


def test_long_ad_sections_and_completion_survive_reanalysis(tmp_path, monkeypatch):
    db = Database(tmp_path / 'db')
    original = ('Background paragraph for the research project.\n' * 250) + 'Upload a CV.'
    job = db.add_job(original)
    seen = []
    def extract(self, text):
        seen.append(text)
        analysis = Analysis(**{k: Fact(value=None, source_quote=None) for k in FACT_FIELDS}, requirements=[])
        if 'Upload a CV.' in text:
            analysis.requirements = [Requirement(category='document', text='Upload a CV.', source_quote='Upload a CV.', importance='mandatory')]
        return analysis, analysis.model_dump_json()
    monkeypatch.setattr(OllamaClient, 'extract', extract)
    analysis = analyze_job(db, job, Settings())
    assert len(seen) > 1 and len(analysis.requirements) == 1
    task = next(t for t in db.tasks(job) if 'Prepare this document' in t['text'])
    db.set_complete(task['id'], True)
    analyze_job(db, job, Settings())
    assert next(t for t in db.tasks(job) if t['text'] == task['text'])['complete'] == 1


def test_combined_document_limit_scope():
    analysis = Analysis(**{k: Fact(value=None, source_quote=None) for k in FACT_FIELDS}, requirements=[Requirement(category='document', text='Upload a CV and a 500-word motivation letter.', source_quote='Upload a CV and a 500-word motivation letter.', importance='mandatory')])
    items = plan_documents(analysis)
    assert next(x for x in items if x['kind'] == 'cv')['word_limit'] is None
    assert next(x for x in items if x['kind'] == 'cover_letter')['word_limit'] == 500
