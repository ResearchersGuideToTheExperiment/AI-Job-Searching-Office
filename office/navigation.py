from office.decisions import decision
from office.cases import FINAL_STATUSES


def selected_jobs(db):
    result=[]
    for job in visible_jobs(db):
        review=decision(db,job['id'])
        if job['status'] not in FINAL_STATUSES and review and review['decision']=='approved':
            result.append(job)
    return result


def rejected_ids(db):
    # Rejection remains visible even when profile changes make evaluation stale.
    with db.connect() as c:
        rows = c.execute("""SELECT j.id FROM jobs j WHERE j.status='Rejected' OR
            (SELECT d.decision FROM evaluation_decisions d WHERE d.job_id=j.id
             ORDER BY d.id DESC LIMIT 1)='rejected'""").fetchall()
    return {row['id'] for row in rows}


def visible_jobs(db):
    rejected = rejected_ids(db)
    return [job for job in db.jobs() if job['id'] not in rejected]


def processing_jobs(db):
    selected = {job['id'] for job in selected_jobs(db)}
    return [job for job in visible_jobs(db) if job['id'] not in selected]
