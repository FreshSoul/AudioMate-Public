"""Windows OS-level restriction layer for the sandbox worker process.

The load-bearing control is a **Job Object**: the worker is assigned to a job
configured so that

  * ``ActiveProcessLimit = 1`` — the worker cannot create ANY child process.
    Even if the in-process Python sandbox were bypassed and code reached
    ``subprocess.Popen('calc')`` / ``os.system(...)`` / a native spawn, Windows
    refuses to create the child. This is the OS boundary that makes
    "escape → execute a program" fail regardless of Python-level holes.
  * ``KILL_ON_JOB_CLOSE`` — when the host closes the job handle (cancel, normal
    completion, or host crash), the worker and anything it managed to start die
    with it. This is the hard kill / cleanup guarantee.
  * a process memory cap — a runaway allocation is bounded.
  * UI restrictions — no desktop / clipboard / global-atom reach.

NOT attempted here (documented limitation): a restricted/low-box token to
ACL-block filesystem *reads*. That requires CreateProcessAsUser /
CreateProcessWithTokenW (privileges a normal user app lacks) or AppContainer
(complex, breaks legitimate Wwise project reads). Read restriction is handled at
the Python layer in the worker instead; OS-level read ACL is future work.

On non-Windows platforms every function is a no-op so the host code path is
identical; process isolation still holds (separate process + kill), just
without the Windows-specific Job Object guarantees.
"""

from __future__ import annotations

import sys

from src.utils.app_logger import get_logger

logger = get_logger(__name__)

IS_WINDOWS = sys.platform == "win32"

# Default worker memory cap (bytes). Generous — heavy audio work runs in the
# MAIN process via RPC, not in the worker, so the worker needs little.
_DEFAULT_MEMORY_CAP = 512 * 1024 * 1024  # 512 MiB


class JobHandle:
    """Owns a Windows Job Object handle. Closing it kills the assigned worker
    (KILL_ON_JOB_CLOSE). A no-op placeholder on non-Windows."""

    def __init__(self, handle=None):
        self._handle = handle

    @property
    def active(self) -> bool:
        return self._handle is not None

    def close(self):
        if self._handle is None:
            return
        try:
            import win32api
            win32api.CloseHandle(self._handle)
        except Exception:
            pass
        finally:
            self._handle = None


def apply_restrictions(proc, *, memory_cap: int = _DEFAULT_MEMORY_CAP) -> JobHandle:
    """Assign ``proc`` (a subprocess.Popen) to a restrictive Job Object.

    Returns a :class:`JobHandle` the caller MUST keep alive for the worker's
    lifetime and close when done (closing it kills the worker). On any failure
    or on non-Windows, returns an inert handle and the worker simply runs
    without the Job Object (process isolation still applies).
    """
    if not IS_WINDOWS:
        return JobHandle(None)

    try:
        import win32job
        import win32api
        import win32con  # noqa: F401  (ensures pywin32 win32con is importable)
    except Exception as exc:
        logger.warning("pywin32 unavailable; sandbox worker runs without Job Object: %s", exc)
        return JobHandle(None)

    try:
        job = win32job.CreateJobObject(None, "")

        # --- extended limits: no children, memory cap, kill-on-close ---
        info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        basic = info["BasicLimitInformation"]
        basic["LimitFlags"] = (
            win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | win32job.JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
        )
        basic["ActiveProcessLimit"] = 1  # the worker itself; no children allowed
        info["BasicLimitInformation"] = basic
        info["ProcessMemoryLimit"] = int(memory_cap)
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)

        # --- UI restrictions: deny desktop / clipboard / handles reach ---
        try:
            ui = win32job.QueryInformationJobObject(job, win32job.JobObjectBasicUIRestrictions)
            ui = (
                win32job.JOB_OBJECT_UILIMIT_DESKTOP
                | win32job.JOB_OBJECT_UILIMIT_DISPLAYSETTINGS
                | win32job.JOB_OBJECT_UILIMIT_GLOBALATOMS
                | win32job.JOB_OBJECT_UILIMIT_HANDLES
                | win32job.JOB_OBJECT_UILIMIT_READCLIPBOARD
                | win32job.JOB_OBJECT_UILIMIT_WRITECLIPBOARD
                | win32job.JOB_OBJECT_UILIMIT_SYSTEMPARAMETERS
            )
            win32job.SetInformationJobObject(job, win32job.JobObjectBasicUIRestrictions, ui)
        except Exception:
            pass  # UI restrictions are a bonus; never fail the whole assignment over them

        # --- assign the worker process to the job ---
        # proc._handle is the Windows process HANDLE from subprocess on Windows.
        proc_handle = int(getattr(proc, "_handle", 0)) or None
        if proc_handle is None:
            # Fall back to opening by PID with the rights needed to assign.
            import win32api as _w
            PROCESS_SET_QUOTA = 0x0100
            PROCESS_TERMINATE = 0x0001
            proc_handle = _w.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, proc.pid)
        win32job.AssignProcessToJobObject(job, proc_handle)

        logger.info("Sandbox worker pid=%s assigned to restrictive Job Object", proc.pid)
        return JobHandle(job)
    except Exception as exc:
        # Nested-job restrictions on old Windows, missing rights, etc. Degrade to
        # process-isolation-only rather than break code execution.
        logger.warning("Failed to assign sandbox worker to Job Object (running without it): %s", exc)
        try:
            win32api.CloseHandle(job)
        except Exception:
            pass
        return JobHandle(None)
