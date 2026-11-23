"""Cross-process per-job exclusion, separate from the shared GPU lock."""
from functools import wraps


def exclusive_job(fn):
    @wraps(fn)
    def wrapped(db,job_id,*args,**kwargs):
        import msvcrt
        directory=db.path.parent/'job-locks'
        directory.mkdir(exist_ok=True)
        with (directory/f'{int(job_id)}.lock').open('a+b') as handle:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as exc:
                raise ValueError(f'Job #{job_id} is already being processed; no second operation started.') from exc
            try:
                return fn(db,job_id,*args,**kwargs)
            finally:
                handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
    return wrapped
