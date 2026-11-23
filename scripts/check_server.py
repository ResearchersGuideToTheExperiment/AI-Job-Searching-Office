"""Start an isolated local dashboard, check HTTP readiness, then stop it."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import requests

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as directory:
    env = dict(os.environ, JOB_OFFICE_DATA_DIR=directory)
    with (root / 'server-smoke.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', str(root / 'app.py'),
            '--server.address', '127.0.0.1', '--server.port', '18501', '--server.headless', 'true'],
            cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        session = requests.Session()
        session.trust_env = False
        try:
            for attempt in range(30):
                if process.poll() is not None:
                    raise RuntimeError('Dashboard process exited; inspect server-smoke.log')
                try:
                    response = session.get('http://127.0.0.1:18501/_stcore/health', timeout=2)
                    if response.status_code == 200:
                        page = session.get('http://127.0.0.1:18501', timeout=2)
                        assert page.status_code == 200
                        print('PASS: Streamlit health and dashboard HTTP response on loopback.')
                        break
                except requests.ConnectionError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError('Dashboard did not become ready')
        finally:
            process.terminate()
            process.wait(timeout=15)
