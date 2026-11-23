import json
from pathlib import Path
import pytest
from office.db import Database
from office.cases import reconcile,correct_text,delete_case
from office.control import request
from office.autonomous import initialize
from office.evaluation import evaluation_current
from office.decisions import save_decision,decision
from test_activity_decisions import fixture


def test_status_change_and_text_correction_queue_evaluation(tmp_path):
    db=Database(tmp_path/'office.sqlite3');job=fixture(db);initialize(db)
    assert evaluation_current(db,job,db.evaluation(job))
    db.set_status(job,'Preparing')
    assert not evaluation_current(db,job,db.evaluation(job))
    reconcile(db)
    with db.connect() as c:
        assert c.execute('SELECT state FROM office_queue WHERE job_id=?',(job,)).fetchone()[0]=='assessed'
    original=db.job(job)['original']
    correct_text(db,job,'Research Associate. This is the corrected complete vacancy. Applicants need relevant research experience. Upload a CV and provide a supporting statement.')
    assert db.job(job)['analysis'] is None and db.job(job)['original']==original
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM case_revisions WHERE job_id=?',(job,)).fetchone()[0]==1


def test_selection_and_hold_and_dirty_invalidation(tmp_path):
    db=Database(tmp_path/'office.sqlite3');job=fixture(db)
    evaluation=db.evaluation(job)
    save_decision(db,job,evaluation['id'],60,'approved')
    assert decision(db,job)['decision']=='approved'
    save_decision(db,job,evaluation['id'],60,'waiting')
    assert decision(db,job)['decision']=='waiting'
    save_decision(db,job,evaluation['id'],60,'approved')
    db.set_status(job,'Reviewing')
    assert decision(db,job) is None


def test_delete_case_forgets_discovery_but_preserves_profile(tmp_path):
    db=Database(tmp_path/'office.sqlite3');job=fixture(db);initialize(db)
    with db.connect() as c:
        c.execute("UPDATE jobs SET source_url='https://www.jobs.ac.uk/job/SYN003/research-associate' WHERE id=?",(job,))
        c.execute("INSERT INTO office_queue(url,job_id,identity,state) VALUES(?,?,?,?)",('https://www.jobs.ac.uk/job/SYN003/research-associate',job,'old-hash','prepared_review_required'))
    request(db,'stopped');delete_case(db,job)
    assert not db.jobs() and db.facts(True)
    with db.connect() as c:
        assert not c.execute('SELECT * FROM office_queue').fetchall()
    # Same URL is accepted after the deletion; no historical dedup record survives.
    new=db.add_job('A fresh original','https://www.jobs.ac.uk/job/SYN003/research-associate')
    reconcile(db)
    assert db.job(new)['original']=='A fresh original'


def test_synthetic_source_and_cached_analysis(tmp_path,monkeypatch):
    from office.retrieval import Page,parse_page,import_url
    from office.service import analyze_job
    from office.ollama import OllamaClient
    from office.config import Settings
    from office.evaluation import evaluate_job,CriterionMatch
    from test_vacancy_pipeline import empty
    url='https://www.jobs.ac.uk/job/SYN003/research-associate'
    raw=(Path(__file__).parent/'fixtures/research_associate.html').read_bytes()
    page=Page(url,raw,'text/html');parse_page(page,url)
    assert page.identity_title=='Research Associate'
    assert page.metadata_facts['institution'][0]=='Example Institute - Research Department'
    assert '£40,000 to £45,000' in page.metadata_facts['salary'][0]
    assert page.metadata_facts['deadline'][0]=='29th November 2026'
    assert page.metadata_facts['application_url'][0]=='https://careers.example.org/vacancies/200/research-associate.html'
    for wrong in ('More jobs','Create Account','Privacy Policy','Main-content extraction'):
        assert wrong not in page.text
    assert page.text.count("Help Improve Sample Measurement")==1
    class Retriever:
        def fetch(self,url):
            return Page(url,raw,'text/html')
    db=Database(tmp_path/'office.sqlite3');job,_=import_url(db,url,Retriever())
    db.save_fact(None,'research','Research experience.',True)
    calls=[]
    def extract(self,text):
        calls.append(text)
        result=empty();return result,result.model_dump_json()
    monkeypatch.setattr(OllamaClient,'extract',extract)
    result=analyze_job(db,job,Settings())
    assert result.salary.value.startswith('£40,000')
    analyze_job(db,job,Settings())
    assert len(calls)==1  # Unchanged extraction reused, no extra model call.
    payload=evaluate_job(db,job,Settings(),automatic=True)
    assert payload['score'] is None  # No invented criteria; still a finished evaluation.
    assert evaluation_current(db,job,db.evaluation(job))


def test_equivalent_explicit_date():
    from office.models import ground_analysis,Fact
    from test_vacancy_pipeline import empty
    a=empty();a.deadline=Fact(value='2026-11-29',source_quote='Closes: 29th November 2026')
    result,warnings=ground_analysis(a,'Closes: 29th November 2026')
    assert result.deadline.value=='29th November 2026' and not warnings


def test_window_presence_expires(tmp_path):
    from office.case_worker import touch,present
    db=Database(tmp_path/'office.sqlite3')
    assert not present(db)
    touch(db,'window');assert present(db)
    with db.connect() as c:
        c.execute("UPDATE dashboard_presence SET heartbeat=datetime('now','-1 minute')")
    assert not present(db)
