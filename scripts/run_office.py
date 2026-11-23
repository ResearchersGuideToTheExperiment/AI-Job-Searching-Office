import sys
import json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if '--due' in sys.argv or sys.stdout is None:
    import os
    log_root=Path(os.environ.get('JOB_OFFICE_DATA_DIR',str(Path(__file__).resolve().parents[1]/'data')))
    log_root.mkdir(parents=True,exist_ok=True)
    sys.stdout=sys.stderr=(log_root/'scheduled-office.log').open('a',encoding='utf-8',buffering=1)
from office.autonomous import run

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--due',action='store_true')
    parser.add_argument('--max-jobs',type=int)
    parser.add_argument('--agent',type=int,choices=[1,2,3])
    parser.add_argument('--approved-only',action='store_true')
    parser.add_argument('--wait',action='store_true')
    parser.add_argument('--continuous',action='store_true')
    parser.add_argument('--parent-pid',type=int)
    args = parser.parse_args()
    if args.due:
        print('Scheduled execution is disabled. Start the system manually.',flush=True)
        sys.exit(0)
    import os
    from office.lifecycle import watch_parent
    watch_parent(args.parent_pid or os.getppid())
    if args.continuous:
        from office.case_worker import run_continuous
        run_continuous()
        sys.exit(0)
    import time
    from office.control import Cancelled
    while True:
        from office.control import state
        from office.config import DATA
        from office.db import Database
        if state(Database(DATA/'office.sqlite3'))['mode'] in {'stopped','cleaning'}:
            print('Office stopped; no work started.',flush=True)
            break
        try:
            result=run(max_jobs=args.max_jobs,approved_only=args.approved_only,agent=args.agent)
            print(json.dumps(result,indent=2),flush=True)
            break
        except Cancelled as exc:
            print(str(exc),flush=True)
            break
        except RuntimeError as exc:
            if not (args.approved_only or args.wait) or str(exc)!='A research run is already active.':
                raise
            time.sleep(30)  # Approved work waits for the single existing office worker.
