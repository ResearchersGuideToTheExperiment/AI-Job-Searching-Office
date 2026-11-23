"""Case lifecycle, explicit revisions and rediscoverable deletion."""
import json
from office.job_lock import exclusive_job

FINAL_STATUSES={'Rejected','Withdrawn','Submitted manually','Interview','Offer'}


def invalidate(db,job_id,reason):
    from office.autonomous import initialize
    initialize(db)
    with db.connect() as c:
        c.execute('INSERT OR IGNORE INTO case_state(job_id) VALUES(?)',(job_id,))
        c.execute("UPDATE case_state SET revision=revision+1,evaluation_dirty=1,selected=0,stage='evaluation_pending',issue=?,changed=CURRENT_TIMESTAMP WHERE job_id=?",(reason,job_id))
        c.execute("UPDATE office_queue SET state='assessed',attempts=0,next_retry_at=NULL,error=NULL WHERE job_id=?",(job_id,))


def reconcile(db):
    """Queue saved cases even when they no longer appear on the current listing."""
    from office.evaluation import evaluation_current
    from office.analysis_input import needs_refresh
    from office.navigation import rejected_ids
    rejected = rejected_ids(db)
    for row in db.jobs():
        if row['id'] in rejected or row['status'] in FINAL_STATUSES:
            continue
        with db.connect() as c:
            case=c.execute('SELECT * FROM case_state WHERE job_id=?',(row['id'],)).fetchone()
            entry=c.execute('SELECT * FROM office_queue WHERE job_id=?',(row['id'],)).fetchone()
        if entry and entry['state'] in {'blocked','needs_manual_review','excluded_role','duplicate'}:
            continue
        needs=not row['analysis'] or needs_refresh(db,row['id']) or not evaluation_current(db,row['id'],db.evaluation(row['id']))
        if needs:
            with db.connect() as c:
                if entry:
                    c.execute("UPDATE office_queue SET state='assessed' WHERE url=? AND state NOT IN ('failed','new')",(entry['url'],))
                else:
                    c.execute("INSERT INTO office_queue(url,source,title,job_id,state) VALUES(?,?,?,?, 'assessed')",
                              (f'manual:job/{row["id"]}','Saved case',f'Job #{row["id"]}',row['id']))
        elif case and case['stage'] not in {'prepared','needs_review'}:
            with db.connect() as c:
                c.execute("UPDATE case_state SET stage='evaluated',issue='' WHERE job_id=?",(row['id'],))


@exclusive_job
def correct_text(db,job_id,text):
    if len(text.strip())<120:
        raise ValueError('Supply the complete, isolated advertisement (at least 120 characters).')
    job=db.job(job_id)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        snapshot={k:v for k,v in job.items() if k!='original_file'}
        snapshot['review']=[dict(r) for r in c.execute('SELECT * FROM analysis_reviews WHERE job_id=?',(job_id,))]
        c.execute('INSERT INTO case_revisions(job_id,reason,snapshot) VALUES(?,?,?)',(job_id,'User corrected advertisement text',json.dumps(snapshot)))
        c.execute('DELETE FROM analysis_reviews WHERE job_id=?',(job_id,))
        c.execute('UPDATE jobs SET analysis=NULL,warnings=? WHERE id=?',('[]',job_id))
        c.execute('INSERT OR IGNORE INTO case_state(job_id) VALUES(?)',(job_id,))
        c.execute('UPDATE case_state SET text_override=? WHERE job_id=?',(text.strip(),job_id))
    invalidate(db,job_id,'Advertisement corrected; extraction and evaluation queued')


@exclusive_job
def delete_case(db,job_id):
    """Remove discovery memory too. The next listing scan may import it anew."""
    from office.advertisement import vacancy_key
    from office.control import state
    if state(db)['mode']!='stopped':
        raise ValueError('Stop the office before deleting a case.')
    job=db.job(job_id)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM processing_sessions WHERE heartbeat>=datetime('now','-90 seconds')").fetchone():
            raise ValueError('Wait for the current worker to stop.')
        packages=[r[0] for r in c.execute('SELECT id FROM packages WHERE job_id=?',(job_id,))]
        for package in packages:
            c.execute('DELETE FROM drafts WHERE package_id=?',(package,))
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'office_queue' in tables:
            for entry in c.execute('SELECT url,job_id FROM office_queue').fetchall():
                if entry['job_id']==job_id or entry['url']==job['source_url'] or (vacancy_key(job['source_url']) and vacancy_key(entry['url'])==vacancy_key(job['source_url'])):
                    c.execute('DELETE FROM office_queue WHERE url=?',(entry['url'],))
        for table in ('packages','evaluations','evaluation_decisions','requirements','tasks','history','sources','analysis_reviews','analysis_inputs','analysis_evidence','operations','agent_activity','case_state','case_revisions','inference_metrics','extraction_cache','evaluation_steps'):
            c.execute(f'DELETE FROM {table} WHERE job_id=?',(job_id,))
        c.execute('DELETE FROM jobs WHERE id=?',(job_id,))
        c.execute('UPDATE office_worker SET discovered=NULL WHERE id=1')
    # Existing exported files remain on disk; this control explicitly deletes database records.
