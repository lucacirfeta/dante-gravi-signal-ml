import os
import subprocess
import sys

import pytest

from src.dante_workflow.processes import process_alive


def test_probe_keeps_real_child_alive_and_detects_exit():
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; print('ready',flush=True); sys.stdin.readline(); print('survived',flush=True)"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    try:
        assert child.stdout.readline().strip() == "ready"
        for _ in range(3):
            assert process_alive(child.pid)
            assert child.poll() is None
        output, _ = child.communicate("finish\n", timeout=10)
        assert "survived" in output
        assert child.returncode == 0
        assert not process_alive(child.pid)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific no-signal regression")
def test_windows_probe_never_calls_os_kill(monkeypatch):
    def forbidden(*args):
        raise AssertionError("liveness must not signal on Windows")
    monkeypatch.setattr(os, "kill", forbidden)
    assert process_alive(os.getpid())


@pytest.mark.parametrize("pid", [0, -1, True, "123"])
def test_invalid_pid_is_rejected(pid):
    with pytest.raises(ValueError):
        process_alive(pid)
