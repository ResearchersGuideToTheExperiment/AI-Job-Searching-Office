import json
import pytest
from office.db import Database
from office.activity import activity,snapshot
from office.decisions import save_decision,decision,require_approval
from office.documents import prepare_package
from office.models import Analysis,Fact,FACT_FIELDS
from office.career import profile_fingerprint
from office.evaluation import analysis_fingerprint
from office.status_ui import analysis_status,suitability


def fixture(db):
    job=db.add_job('Research job')
    analysis=Analysis(**{k:Fact(value=None,source_quote=None) for k in FACT_FIELDS},requirements=[])
    with db.connect() as c:
        c.execute('UPDATE jobs SET analysis=? WHERE id=?',(analysis.model_dump_json(),job))
    db.save_fact(None,'research','Tested perception.',True)
    db.save_evaluation(job,profile_fingerprint(db.facts(True)),analysis_fingerprint(analysis),{'score':60,'criteria':[]})
    return job


def test_approval_is_persistent_and_invalidated_by_profile_change(tmp_path):
    db=Database(tmp_path/'office.db')
    job=fixture(db)
    with pytest.raises(ValueError,match='Approve'):
        prepare_package(db,job)
    ident=db.evaluation(job)['id']
    with pytest.raises(ValueError,match='reason'):
        save_decision(db,job,ident,90,'approved')
    save_decision(db,job,ident,90,'approved','Transferable experience meets the requirement.')
    assert decision(Database(db.path),job)['score']==90
    assert json.loads(db.evaluation(job)['payload'])['score']==60
    save_decision(db,job,ident,60,'rejected')
    with pytest.raises(ValueError,match='Approve'):
        require_approval(db,job)
    save_decision(db,job,ident,60,'approved')
    db.save_fact(None,'skills','Python.',True)
    assert decision(db,job) is None
    with pytest.raises(ValueError,match='changed'):
        save_decision(db,job,ident,60,'approved')


def test_activity_success_failure_and_interruption(tmp_path):
    db=Database(tmp_path/'office.db')
    with activity(db,1,'Searching for jobs'):
        assert snapshot(db)[0][0]['label']=='Searching for jobs'
    assert snapshot(db)[1][0]['state']=='completed'
    with pytest.raises(ValueError):
        with activity(db,2,'Evaluating suitability'):
            raise ValueError('Connection failed')
    assert snapshot(db)[1][0]['state']=='failed'
    with db.connect() as c:
        c.execute("INSERT INTO agent_activity(agent,label,heartbeat) VALUES(3,'Preparing documents',datetime('now','-2 minutes'))")
    assert not snapshot(db)[0]
    assert snapshot(db)[1][0]['state']=='interrupted'


def test_separate_analysis_and_fit_colours(tmp_path):
    db=Database(tmp_path/'office.db')
    job=fixture(db)
    assert analysis_status(db,db.job(job))==('Analysis successful','green')
    assert suitability(90)[1]=='green'
    assert suitability(60)[1]=='yellow'
    assert suitability(20)[1]=='red'
    assert suitability(None)[1]=='neutral'
    with db.connect() as c:
        c.execute("INSERT INTO history(job_id,outcome) VALUES(?,'failed')",(job,))
    assert analysis_status(db,db.job(job))[1]=='yellow'
    with db.connect() as c:
        c.execute('UPDATE jobs SET analysis=NULL WHERE id=?',(job,))
    assert analysis_status(db,db.job(job))[1]=='red'
