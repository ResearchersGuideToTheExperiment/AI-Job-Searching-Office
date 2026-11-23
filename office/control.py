"""Cross-process cooperative control and cleanup interlock."""
import contextvars
import threading
import time
import uuid
from contextlib import contextmanager

CURRENT=contextvars.ContextVar('office_control',default=None)


class Cancelled(BaseException):
    """Deliberately bypass per-job retry handlers."""


def state(db):
    with db.connect() as c:
        return dict(c.execute('SELECT * FROM office_control WHERE id=1').fetchone())


def request(db,mode):
    if mode not in {'running','paused','stopped'}:
        raise ValueError('Invalid control mode')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        current=c.execute('SELECT mode FROM office_control WHERE id=1').fetchone()['mode']
        if current=='cleaning':
            raise ValueError('Data cleanup is in progress. Wait for it to finish.')
        c.execute('UPDATE office_control SET mode=?,generation=generation+? WHERE id=1',
                  (mode,int(mode=='stopped')))


def checkpoint():
    context=CURRENT.get()
    if not context:
        return
    db,generation,ident=context
    while True:
        mode=state(db)
        if mode['generation']!=generation or mode['mode'] in {'stopped','cleaning'}:
            raise Cancelled('Stopped by user; completed work is retained.')
        with db.connect() as c:
            c.execute('UPDATE processing_sessions SET state=? WHERE id=?',(mode['mode'],ident))
        if mode['mode']=='running':
            return
        time.sleep(.5)


@contextmanager
def session(db):
    if CURRENT.get():
        checkpoint()
        yield
        return
    ident=uuid.uuid4().hex
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        mode=dict(c.execute('SELECT * FROM office_control WHERE id=1').fetchone())
        if mode['mode']!='running':
            raise Cancelled('Office is paused or stopped. Resume it in the activity panel.')
        import os
        c.execute('INSERT INTO processing_sessions(id,owner_pid) VALUES(?,?)',(ident,os.getpid()))
    token=CURRENT.set((db,mode['generation'],ident))
    stop=threading.Event()
    def heartbeat():
        while not stop.wait(10):
            try:
                with db.connect() as c:
                    c.execute('UPDATE processing_sessions SET heartbeat=CURRENT_TIMESTAMP WHERE id=?',(ident,))
            except Exception:
                pass
    worker=threading.Thread(target=heartbeat,daemon=True)
    worker.start()
    try:
        yield
        checkpoint()
    finally:
        stop.set(); worker.join(timeout=1)
        CURRENT.reset(token)
        with db.connect() as c:
            c.execute('DELETE FROM processing_sessions WHERE id=?',(ident,))
