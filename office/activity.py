"""Persistent major-stage activity shared by dashboard and background workers."""
import threading
import contextvars
from contextlib import contextmanager
from functools import wraps
from office.control import session,checkpoint,Cancelled
ACTIVE_JOB=contextvars.ContextVar('active_job',default=None)


@contextmanager
def _activity(db, agent, label, job_id=None):
    import os
    token=ACTIVE_JOB.set(job_id if job_id is not None else ACTIVE_JOB.get())
    with db.connect() as c:
        ident=c.execute('INSERT INTO agent_activity(agent,label,job_id,owner_pid) VALUES(?,?,?,?)',
                        (agent,label,job_id,os.getpid())).lastrowid
    stop=threading.Event()
    def heartbeat():
        while not stop.wait(10):
            try:
                with db.connect() as c:
                    c.execute('UPDATE agent_activity SET heartbeat=CURRENT_TIMESTAMP WHERE id=?',(ident,))
            except Exception:
                pass
    worker=threading.Thread(target=heartbeat,daemon=True)
    worker.start()
    state,detail='completed',''
    try:
        checkpoint()
        yield
        checkpoint()
    except Cancelled as exc:
        state,detail='stopped',str(exc)
        if job_id is not None:
            with db.connect() as c:
                c.execute("UPDATE history SET outcome='stopped',detail=?,finished_at=CURRENT_TIMESTAMP WHERE job_id=? AND outcome='running'",(detail,job_id))
                c.execute("UPDATE operations SET state='stopped',detail=?,finished_at=CURRENT_TIMESTAMP WHERE job_id=? AND state='running'",(detail,job_id))
        raise
    except BaseException as exc:
        state,detail='failed',str(exc)
        raise
    finally:
        stop.set()
        worker.join(timeout=1)
        with db.connect() as c:
            c.execute('UPDATE agent_activity SET state=?,detail=?,finished=CURRENT_TIMESTAMP WHERE id=?',
                      (state,detail,ident))
        ACTIVE_JOB.reset(token)


@contextmanager
def activity(db,agent,label,job_id=None):
    with session(db), _activity(db,agent,label,job_id):
        yield


def tracked(agent,label):
    def decorate(fn):
        @wraps(fn)
        def wrapped(db,job_id,*args,**kwargs):
            with activity(db,agent,label,job_id):
                return fn(db,job_id,*args,**kwargs)
        return wrapped
    return decorate


def snapshot(db):
    with db.connect() as c:
        c.execute("UPDATE agent_activity SET state='interrupted',finished=heartbeat,detail='Worker stopped responding; retry the task.' WHERE state='running' AND heartbeat < datetime('now','-90 seconds')")
        active=[dict(r) for r in c.execute("SELECT * FROM agent_activity WHERE state='running' ORDER BY id DESC")]
        history=[dict(r) for r in c.execute("SELECT * FROM agent_activity WHERE state!='running' ORDER BY id DESC LIMIT 30")]
    return active,history
