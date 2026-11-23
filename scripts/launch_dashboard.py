"""Double-click launcher: reuse a healthy server or start one locally."""
from pathlib import Path
import subprocess
import sys
import time
import webbrowser
import requests

ROOT = Path(__file__).resolve().parents[1]
URL = 'http://127.0.0.1:8501'


def ready(session):
    try:
        return session.get(URL + '/_stcore/health', timeout=1).status_code == 200
    except requests.RequestException:
        return False


def main():
    session = requests.Session()
    session.trust_env = False
    if ready(session):
        webbrowser.open(URL)
        return
    print('Starting Job Application Office. Keep this window open while using it.')
    process = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', str(ROOT / 'app.py'),
                                '--server.address', '127.0.0.1', '--server.port', '8501',
                                '--server.headless', 'true'], cwd=ROOT)
    try:
        for _ in range(40):
            if process.poll() is not None:
                raise RuntimeError('Dashboard could not start. See the message above.')
            if ready(session):
                webbrowser.open(URL)
                print('Dashboard opened. Press Ctrl+C here to stop it.')
                process.wait()
                return
            time.sleep(.5)
        raise RuntimeError('Dashboard startup timed out. Check the messages above.')
    except KeyboardInterrupt:
        pass
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=15)


if __name__ == '__main__':
    main()
