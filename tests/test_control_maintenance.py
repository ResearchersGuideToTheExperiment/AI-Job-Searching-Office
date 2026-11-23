import threading
import pytest
from office.db import Database
from office.control import session,request,state,checkpoint,Cancelled
from office.maintenance import clear_sections
from office.activity import activity,snapshot
from test_activity_decisions import fixture


def test_stop_cancels_session_even_if_resumed_before_checkpoint(tmp_path):
    db=Database(tmp_path/'office.db')
    with pytest.raises(Cancelled):
        with session(db),activity(db,1,'Searching'):
            request(db,'stopped')
            request(db,'running')
            checkpoint()
    assert snapshot(db)[1][0]['state']=='stopped'
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM processing_sessions').fetchone()[0]==0


def test_pause_and_resume(tmp_path):
    db=Database(tmp_path/'office.db')
    ready=threading.Event(); proceed=threading.Event(); done=threading.Event()
    def work():
        with session(db):
            ready.set(); proceed.wait(3)
            checkpoint()
            done.set()
    worker=threading.Thread(target=work)
    worker.start()
    try:
        assert ready.wait(3)
        request(db,'paused'); proceed.set()
        assert not done.wait(.2)
        request(db,'running')
        assert done.wait(3)
    finally:
        request(db,'running'); proceed.set(); worker.join(3)


def test_cleanup_requires_stopped_and_excludes_active_worker(tmp_path):
    db=Database(tmp_path/'office.db')
    job=fixture(db)
    with pytest.raises(ValueError,match='Stop'):
        clear_sections(db,['jobs'])
    with pytest.raises(Cancelled):
        with session(db):
            request(db,'stopped')
            with pytest.raises(ValueError,match='worker'):
                clear_sections(db,['jobs'])
    assert db.job(job)
    clear_sections(db,['jobs'])
    assert not db.jobs()
    assert len(db.facts(True))==1
    assert state(db)['mode']=='stopped'


def test_package_cleanup_deletes_only_owned_files_and_keeps_jobs(tmp_path):
    db=Database(tmp_path/'office.db')
    job=fixture(db)
    path=tmp_path/'applications'/'job-1'/'draft.docx'
    path.parent.mkdir(parents=True); path.write_bytes(b'test')
    with db.connect() as c:
        package=c.execute('INSERT INTO packages(job_id,evaluation_id,plan) VALUES(?,?,?)',(job,db.evaluation(job)['id'],'[]')).lastrowid
        c.execute('INSERT INTO drafts(package_id,file_path) VALUES(?,?)',(package,str(path)))
    request(db,'stopped')
    clear_sections(db,['packages'])
    assert not path.exists()
    assert db.job(job) and db.evaluation(job)


def test_unsafe_file_path_rolls_back_cleanup(tmp_path):
    db=Database(tmp_path/'office.db')
    job=fixture(db)
    outside=tmp_path/'master.docx'; outside.write_bytes(b'keep')
    with db.connect() as c:
        package=c.execute('INSERT INTO packages(job_id,plan) VALUES(?,?)',(job,'[]')).lastrowid
        c.execute('INSERT INTO drafts(package_id,file_path) VALUES(?,?)',(package,str(outside)))
    request(db,'stopped')
    with pytest.raises(ValueError,match='outside'):
        clear_sections(db,['jobs'])
    assert outside.read_bytes()==b'keep'
    assert db.job(job) and db.package(job)
    assert state(db)['mode']=='stopped'
