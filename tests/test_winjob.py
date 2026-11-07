from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from waker.winjob import WinJob

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-only")


def _sleep_forever() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_job_object_terminates_assigned_process():
    job = WinJob()
    if not job.ok:
        pytest.skip("job object unavailable in this session")
    proc = _sleep_forever()
    try:
        assert job.assign(proc.pid)
        job.terminate()
        proc.wait(timeout=10)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
        job.close()


def test_job_object_unavailable_is_not_fatal():
    job = WinJob()
    job.assign(999_999_999)  # must not raise
    job.terminate()
    job.close()
