"""Inert process-lifetime probe; never invokes the scientific workflow CLI."""

import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.dante_workflow.ui.controller import (  # noqa: E402
    LocalPathPolicy, UISelection, WorkflowUIController,
)
from src.dante_workflow.ui import controller as controller_module  # noqa: E402


def main():
    mode, directory = sys.argv[1:]
    directory = Path(directory)
    if mode == "child":
        (directory / "child-ready").touch()
        deadline = time.monotonic() + 30
        while not (directory / "release-child").exists():
            if time.monotonic() > deadline:
                return 2
            time.sleep(0.05)
        return 0
    raw, cache = directory / "raw", directory / "cache"
    raw.mkdir()
    cache.mkdir()
    controller = WorkflowUIController(
        selection=UISelection(ROOT, ROOT / "config/dante_workflow_productization_v1.json", raw, cache, None),
        path_policy=LocalPathPolicy(ROOT, (raw,), (cache,)),
    )

    def launch_inert_child(command, **options):
        assert command[2] == "report"
        return subprocess.Popen([sys.executable, __file__, "child", str(directory)], **options)

    controller_module.spawn_worker = launch_inert_child
    print(json.dumps(controller.launch("start")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
