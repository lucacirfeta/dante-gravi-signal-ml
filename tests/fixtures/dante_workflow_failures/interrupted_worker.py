"""Isolated crash-test worker; records one attempt, never runs science."""

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.dante_workflow.schema import load_workflow_spec  # noqa: E402
from src.dante_workflow.state import WorkflowLedger  # noqa: E402


def main():
    directory = Path(sys.argv[1])
    spec = load_workflow_spec(ROOT / "config/dante_workflow_productization_v1.json", root=ROOT)
    ledger = WorkflowLedger.open(directory, spec=spec, run_key="isolated-recovery-fixture")
    lease = ledger.acquire_lease()
    ledger.start_attempt(lease, "PREFLIGHT")
    (directory / "ready").touch()
    # Bounded fallback if the test harness itself dies; no global process names.
    time.sleep(30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
