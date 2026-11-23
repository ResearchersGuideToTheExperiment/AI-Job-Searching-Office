import json
from pathlib import Path
from office import autonomous as a
from office.config import Settings
from office.db import Database
from office.models import Analysis, Fact, Requirement, FACT_FIELDS
from office.career import profile_fingerprint
from office.evaluation import analysis_fingerprint
from office.discovery import discover, canonical
from office.retrieval import Page


def test_adapter_links_and_status():
    class Fixture:
        def fetch(self,url):
            return Page(url,b'<a href="/jobs/123">Researcher</a>','text/html')
    result = discover({'name':'fixture','url':'https://example.org','pattern':r'/jobs/\d+'},Fixture())
    assert result['state']=='working'
    assert result['jobs'][0]['url']=='https://example.org/jobs/123'
    assert canonical('https://example.org/jobs/123?utm_source=x')=='https://example.org/jobs/123'


def test_background_pipeline_prepares_docx_and_does_not_repeat(tmp_path, monkeypatch):
    monkeypatch.setattr(a,'DATA',tmp_path)
    monkeypatch.setattr(a,'config',lambda:a.OfficeSettings(sources=[{'name':'fixture'}]))
    monkeypatch.setattr(a,'load_settings',lambda:Settings())
    monkeypatch.setattr(a,'sync_local_files',lambda db:None)
    monkeypatch.setattr(a,'discover',lambda source:{'state':'working','detail':'fixture','jobs':[{'url':'https://example.org/jobs/123','title':'Researcher','source':'fixture'}]})
    db=Database(tmp_path/'office.sqlite3')
    db.save_fact(None,'research','Tested 40 participants.',True)
    def imported(db,url):
        return db.add_job('Upload a CV.',url),[]
    monkeypatch.setattr(a,'import_url',imported)
    analysis=Analysis(**{k:Fact(value=None,source_quote=None) for k in FACT_FIELDS},requirements=[Requirement(category='document',text='Upload a CV.',source_quote='Upload a CV.',importance='mandatory')])
    def analyzed(db,job_id,settings):
        from office.coordinator import build_tasks
        run=db.start_run(job_id,settings,'fixture')
        db.save_analysis(job_id,analysis,[],build_tasks(analysis,[]),run,'{}')
        return analysis
    monkeypatch.setattr(a,'analyze_job',analyzed)
    monkeypatch.setattr(a.OllamaClient,'structured',lambda *args:a.Relevance(relevant=True,region_match=True,reason='Synthetic match'))
    monkeypatch.setattr(a.OllamaClient,'test_connection',lambda self:'ok')
    def evaluated(db,job_id,settings,automatic=False):
        assert automatic
        assert not db.is_analysis_reviewed(job_id,analysis_fingerprint(analysis))
        payload={'score':95,'criteria':[]}
        db.save_evaluation(job_id,profile_fingerprint(db.facts(True)),analysis_fingerprint(analysis),payload)
        return payload
    monkeypatch.setattr(a,'evaluate_job',evaluated)
    result=a.run()
    assert result['prepared']==0
    assert db.package(1) is None
    from office.decisions import save_decision
    save_decision(db,1,db.evaluation(1)['id'],95,'approved')
    assert a.run(approved_only=True)['prepared']==1
    package=db.package(1)
    drafts=db.drafts(package['id'])
    assert len(drafts)==1 and Path(drafts[0]['file_path']).exists()
    assert db.tasks(1)
    assert a.run()['prepared']==0
    assert len(db.drafts(package['id']))==1
