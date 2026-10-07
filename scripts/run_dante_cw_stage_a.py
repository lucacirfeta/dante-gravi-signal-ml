"""One isolated Stage A run; no automatic scientific follow-up or resume."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def supervise(args):
    """Persist observed child OS exit even if the interactive session is lost."""
    output = Path(args.output)
    if output.exists():
        raise FileExistsError("fresh run output already exists; no resume")
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = output.parent / output.name
    with Path(str(prefix) + ".supervisor.log").open("x", buffering=1) as log:
        command = [sys.executable, "-u", str(Path(__file__).resolve()),
                   "--config", args.config, "--output", args.output,
                   "--config-sha256", args.config_sha256,
                   "--module-sha256", args.module_sha256]
        with Path(str(prefix) + ".stdout.log").open("xb") as stdout, \
                Path(str(prefix) + ".stderr.log").open("xb") as stderr:
            log.write(f"SUPERVISOR_PID={os.getpid()}\n")
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
            log.write(f"CONTROLLER_PID={process.pid}\n")
            code = process.wait()
            log.write(f"RUN_EXIT_CODE={code}\n")
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--module-sha256", required=True)
    parser.add_argument("--supervise", action="store_true")
    args = parser.parse_args()
    if args.supervise:
        return supervise(args)
    contract = json.loads(Path(args.config).read_text())
    threads = str(contract["operations"]["threads_per_worker"])
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = threads
    os.environ["MPLBACKEND"] = "Agg"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.validation.cw_stage_a import run

    print(run(args.config, args.output, args.config_sha256, args.module_sha256), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
