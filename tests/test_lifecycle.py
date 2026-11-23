import os
import subprocess
import sys
import time
from pathlib import Path


def test_worker_exits_when_launching_process_closes(tmp_path):
    root=Path(__file__).resolve().parents[1]
    env=dict(os.environ,JOB_OFFICE_DATA_DIR=str(tmp_path))
    flags=subprocess.CREATE_NO_WINDOW
    parent=subprocess.Popen([sys.executable,'-c','import time; time.sleep(15)'],creationflags=flags)
    child=None
    try:
        code="from office.lifecycle import watch_parent; from pathlib import Path; import sys,time; watch_parent(int(sys.argv[1])); Path(sys.argv[2]).write_text('ready'); time.sleep(15)"
        ready=tmp_path/'ready'
        child=subprocess.Popen([sys.executable,'-c',code,str(parent.pid),str(ready)],cwd=root,env=env,creationflags=flags)
        until=time.monotonic()+5
        while not ready.exists() and time.monotonic()<until:
            time.sleep(.05)
        assert ready.exists() and child.poll() is None
        parent.terminate();parent.wait(timeout=3)
        assert child.wait(timeout=5)==0
    finally:
        for process in (child,parent):
            if process and process.poll() is None:
                process.terminate();process.wait(timeout=3)
