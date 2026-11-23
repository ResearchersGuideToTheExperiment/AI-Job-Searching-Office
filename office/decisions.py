"""User decisions are separate from immutable model evaluation evidence."""
import json
from office.evaluation import evaluation_current


def decision(db,job_id):
    evaluation=db.evaluation(job_id)
    if not evaluation_current(db,job_id,evaluation):
        return None
    with db.connect() as c:
        row=c.execute('SELECT * FROM evaluation_decisions WHERE evaluation_id=? ORDER BY id DESC LIMIT 1',(evaluation['id'],)).fetchone()
    if not row:
        return None
    result=dict(row)
    with db.connect() as c:
        selected=c.execute('SELECT selected FROM case_state WHERE job_id=?',(job_id,)).fetchone()
    if result['decision']=='approved' and selected and not selected['selected']:
        result['decision']='waiting'
    return result


def save_decision(db,job_id,evaluation_id,score,verdict,note=''):
    evaluation=db.evaluation(job_id)
    if not evaluation or evaluation['id']!=evaluation_id or not evaluation_current(db,job_id,evaluation):
        raise ValueError('The evaluation changed. Refresh and review its latest version.')
    if verdict not in {'approved','rejected','waiting'} or not 0<=score<=100:
        raise ValueError('Choose a decision and a score between 0 and 100.')
    if score!=json.loads(evaluation['payload'])['score'] and not note.strip():
        raise ValueError('Add a short reason for correcting the AI score.')
    from office.autonomous import initialize
    initialize(db)
    with db.connect() as c:
        c.execute('INSERT INTO evaluation_decisions(job_id,evaluation_id,score,decision,note) VALUES(?,?,?,?,?)',
                  (job_id,evaluation_id,score,verdict,note.strip()))
        c.execute('UPDATE case_state SET selected=? WHERE job_id=?',(int(verdict=='approved'),job_id))
        existing=c.execute('SELECT url FROM office_queue WHERE job_id=?',(job_id,)).fetchone()
        state='rejected_by_user' if verdict=='rejected' else 'awaiting_approval'
        if existing:
            c.execute('UPDATE office_queue SET state=?,error=NULL WHERE job_id=?',(state,job_id))
            if verdict=='approved':
                c.execute('UPDATE office_queue SET attempts=0 WHERE job_id=?',(job_id,))
        else:
            c.execute('INSERT INTO office_queue(url,source,title,job_id,state) VALUES(?,?,?,?,?)',
                      (f'manual:job/{job_id}','Manual job',f'Job #{job_id}',job_id,state))


def require_approval(db,job_id):
    current=decision(db,job_id)
    if not current or current['decision']!='approved':
        raise ValueError('Approve the current suitability evaluation before preparing documents.')
    return current
