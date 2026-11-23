"""One continuous worker while a dashboard session is present; no busy AI loop."""
import time
import threading
from contextlib import contextmanager


def present(db):
    with db.connect() as c:
        return bool(c.execute("SELECT 1 FROM dashboard_presence WHERE heartbeat>=datetime('now','-45 seconds')").fetchone())


def touch(db,ident):
    with db.connect() as c:
        c.execute('INSERT INTO dashboard_presence(id) VALUES(?) ON CONFLICT(id) DO UPDATE SET heartbeat=CURRENT_TIMESTAMP',(ident,))
        c.execute("DELETE FROM dashboard_presence WHERE heartbeat<datetime('now','-1 day')")


def ensure_worker(db):
    from office.control import state
    if state(db)['mode']!='running':
        return
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM office_worker WHERE id=1 AND heartbeat>=datetime('now','-30 seconds')").fetchone():
            return
        # Reservation prevents simultaneous browser sessions repeatedly launching workers.
        c.execute('INSERT INTO office_worker(id,heartbeat) VALUES(1,CURRENT_TIMESTAMP) ON CONFLICT(id) DO UPDATE SET heartbeat=CURRENT_TIMESTAMP')
    import subprocess,sys,os
    from office.config import ROOT
    with (db.path.parent/'background-office.log').open('a',encoding='utf-8') as log:
        subprocess.Popen([sys.executable,str(ROOT/'scripts/run_office.py'),'--continuous','--parent-pid',str(os.getpid())],cwd=ROOT,
                         stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)


def run_continuous():
    import msvcrt
    from office.config import DATA
    from office.db import Database
    from office.control import state,Cancelled
    from office.autonomous import run
    db=Database(DATA/'office.sqlite3')
    import os
    with (DATA/'continuous-office.lock').open('a+b') as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            return
        with db.connect() as c:
            c.execute('UPDATE office_worker SET owner_pid=? WHERE id=1',(os.getpid(),))
        stop=threading.Event()
        def heartbeat():
            while not stop.wait(5):
                with db.connect() as c:
                    c.execute('INSERT INTO office_worker(id,heartbeat) VALUES(1,CURRENT_TIMESTAMP) ON CONFLICT(id) DO UPDATE SET heartbeat=CURRENT_TIMESTAMP')
        thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
        try:
            while present(db):
                mode=state(db)['mode']
                if mode in {'stopped','cleaning'}:
                    break
                if mode=='paused':
                    time.sleep(2);continue
                with db.connect() as c:
                    due=not c.execute("SELECT 1 FROM office_worker WHERE id=1 AND discovered>=datetime('now','-1 hour')").fetchone()
                if not due:
                    from office.autonomous import initialize
                    from office.cases import reconcile
                    initialize(db);reconcile(db)
                    with db.connect() as c:
                        pending=c.execute("SELECT 1 FROM office_queue q LEFT JOIN case_state s ON q.job_id=s.job_id WHERE (q.state IN ('new','failed','assessed') OR (q.state='awaiting_approval' AND s.selected=1)) AND (q.next_retry_at IS NULL OR q.next_retry_at<=CURRENT_TIMESTAMP)").fetchone()
                    if not pending:
                        time.sleep(10);continue
                try:
                    result=run(max_jobs=1,discover_jobs=due)
                    if due:
                        with db.connect() as c:
                            c.execute('UPDATE office_worker SET discovered=CURRENT_TIMESTAMP WHERE id=1')
                    # No repeated AI calls for completed unchanged cases. Idle checks are SQLite only.
                    time.sleep(2 if result.get('assessed') else 10)
                except Cancelled:
                    if state(db)['mode']!='paused':
                        break
                except Exception as exc:
                    print('Continuous worker:',str(exc),flush=True)
                    time.sleep(15)
        finally:
            stop.set();thread.join(1)
            with db.connect() as c:
                c.execute('UPDATE office_worker SET heartbeat=NULL WHERE id=1')
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
