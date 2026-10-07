"""One fresh isolated descriptive Stage C invocation; no follow-up/resume."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--module-sha256", required=True)
    parser.add_argument("--supervise", action="store_true")
    args = parser.parse_args()
    if args.supervise:
        output = Path(args.output)
        if output.exists():
            raise FileExistsError("fresh output required")
        output.parent.mkdir(parents=True, exist_ok=True)
        prefix = output.parent / output.name
        with Path(str(prefix) + ".supervisor.log").open("x", buffering=1) as log:
            with (
                Path(str(prefix) + ".stdout.log").open("xb") as out,
                Path(str(prefix) + ".stderr.log").open("xb") as err,
            ):
                command = [
                    sys.executable,
                    "-u",
                    __file__,
                    "--config",
                    args.config,
                    "--output",
                    args.output,
                    "--config-sha256",
                    args.config_sha256,
                    "--module-sha256",
                    args.module_sha256,
                ]
                child = subprocess.Popen(command, stdout=out, stderr=err)
                log.write(f"CONTROLLER_PID={child.pid}\n")
                code = child.wait()
                log.write(f"RUN_EXIT_CODE={code}\n")
                return code
    threads = str(json.loads(Path(args.config).read_text())["operations"]["threads"])
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = threads
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.validation.cw_stage_c import run

    print(
        run(args.config, args.output, args.config_sha256, args.module_sha256),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
