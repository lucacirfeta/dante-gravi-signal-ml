import subprocess
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

sessions = ['1389190912', '1371565312', '1369001984', '1376749312', '1375712512']

def run_cmd(cmd):
    logging.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0:
        logging.error(f"Command failed with exit code {result.returncode}:\n{result.stdout}")
    else:
        logging.info("Command completed successfully.")
        # log the last 10 lines of output
        lines = result.stdout.strip().split("\n")
        logging.info("Output tail:\n" + "\n".join(lines[-10:]))

for session in sessions:
    logging.info(f"=== Starting Session {session} ===")
    
    # Run patch-analysis
    cmd_patch = [
        sys.executable, "main.py", "patch-analysis",
        "--detector", "H1",
        "--data-dir", "E:/o4a",
        "--sessions", session,
    ]
    run_cmd(cmd_patch)
    
    # Run production-report
    cmd_report = [
        sys.executable, "main.py", "production-report",
        "--session-id", session,
        "--detector", "H1"
    ]
    run_cmd(cmd_report)
    
logging.info("Pilot analysis complete.")
