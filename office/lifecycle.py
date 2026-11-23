"""Windows workers cannot outlive the dashboard/console that launched them."""
import ctypes
from ctypes import wintypes
import os
import sqlite3
import threading


def watch_parent(pid):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x100000,False,int(pid))
    if not handle:
        raise RuntimeError('Launching system is no longer running; worker not started.')
    def monitor():
        try:
            while kernel.WaitForSingleObject(handle,1000)==258:
                pass
            from office.config import DATA
            try:
                with sqlite3.connect(DATA/'office.sqlite3',timeout=1) as c:
                    for table in ('agent_activity','office_runs'):
                        c.execute(f"UPDATE {table} SET state='interrupted',finished=CURRENT_TIMESTAMP WHERE owner_pid=? AND state='running'",(os.getpid(),))
                    c.execute('DELETE FROM processing_sessions WHERE owner_pid=?',(os.getpid(),))
                    c.execute('UPDATE office_worker SET heartbeat=NULL WHERE owner_pid=?',(os.getpid(),))
            except sqlite3.Error:
                pass
            os._exit(0)  # Also closes outstanding HTTP sockets and releases OS locks.
        finally:
            kernel.CloseHandle(handle)
    threading.Thread(target=monitor,daemon=True).start()
