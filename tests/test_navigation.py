from office.db import Database
from office.navigation import selected_jobs, processing_jobs
from office.decisions import save_decision
from test_activity_decisions import fixture


def test_checklist_selection_and_archiving_preserve_history(tmp_path):
    db = Database(tmp_path / 'office.sqlite3')
    job = fixture(db)
    db.add_job('Another unselected vacancy')
    assert not selected_jobs(db)
    evaluation = db.evaluation(job)
    save_decision(db, job, evaluation['id'], 60, 'approved')
    assert [row['id'] for row in selected_jobs(db)] == [job]
    assert job not in [row['id'] for row in processing_jobs(db)]
    save_decision(db, job, evaluation['id'], 60, 'waiting')
    assert not selected_jobs(db)
    assert job in [row['id'] for row in processing_jobs(db)]
    save_decision(db, job, evaluation['id'], 60, 'approved')
    db.set_status(job, 'Submitted manually')
    assert not selected_jobs(db)
    assert len(db.jobs()) == 2
    assert db.job(job)['original'] == 'Research job'
    assert db.evaluation(job)['id'] == evaluation['id']


def test_rejected_cases_hidden_after_profile_changes_but_retained(tmp_path):
    from office.navigation import visible_jobs, rejected_ids
    from office.cases import reconcile
    db = Database(tmp_path / 'office.sqlite3')
    job = fixture(db)
    other = db.add_job('Another vacancy')
    save_decision(db, job, db.evaluation(job)['id'], 60, 'rejected')
    assert [row['id'] for row in visible_jobs(db)] == [other]
    assert rejected_ids(db) == {job}
    db.save_fact(None, 'skills', 'New confirmed skill.', True)
    reconcile(db)
    assert rejected_ids(db) == {job}
    assert job not in [row['id'] for row in visible_jobs(db)]
    assert db.job(job)['original'] == 'Research job'
    with db.connect() as c:
        assert c.execute('SELECT state FROM office_queue WHERE job_id=?', (job,)).fetchone()['state'] == 'rejected_by_user'
