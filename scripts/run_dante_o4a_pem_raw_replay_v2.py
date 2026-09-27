#!/usr/bin/env python3
"""Preflight, acquire or verify the URL-corrected O4a PEM raw replay."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError  # noqa: E402
from src.dante_light.o3a_o4a_common_pem_contract_v2 import (  # noqa: E402
    load_contract as load_common_v2_contract,
)
from src.dante_light.o4a_pem_raw_replay import (  # noqa: E402
    _host_path,
    load_targets,
    parse_manifest,
    required_frames,
)
from src.dante_light.o4a_pem_raw_replay_v2 import (  # noqa: E402
    archive_url,
    load_contract as load_raw_v2_contract,
    run_replay,
    verify_replay,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", choices=("preflight", "run", "verify"), required=True
    )
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    comparison = load_common_v2_contract(root=ROOT)
    raw = load_raw_v2_contract(root=ROOT)
    external_root = _host_path(raw["output"]["external_root_windows"]).resolve()
    if args.stage == "preflight":
        if args.run_dir is not None:
            parser.error("--run-dir is only valid with --stage verify")
        targets = load_targets(raw)
        with urlopen(raw["source"]["manifest_url"], timeout=60) as response:
            manifest_bytes = response.read()
        manifest = parse_manifest(manifest_bytes, raw["source"]["release"])
        frames = required_frames(targets, manifest)
        checked: dict[str, str] = {}
        for detector in ("H1", "L1"):
            frame = next(item for item in frames if item["detector"] == detector)
            url = archive_url(frame, raw["source"])
            with urlopen(Request(url, method="HEAD"), timeout=60) as response:
                if response.status != 200:
                    raise ContractError(
                        "GWOSC archive URL preflight did not return 200"
                    )
            checked[detector] = url
        result = {
            "status": "PASS_O4A_PEM_RAW_REPLAY_V2_PREFLIGHT",
            "comparison_contract_digest": comparison["contract_digest"],
            "raw_contract_digest": raw["contract_digest"],
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "target_count": len(targets),
            "frame_count": len(frames),
            "head_200_by_detector": checked,
            "strain_opened": False,
            "pem_outcomes_opened": False,
        }
    elif args.stage == "run":
        if args.run_dir is not None:
            parser.error("--run-dir is only valid with --stage verify")
        summary, run_dir = run_replay(root=ROOT, external_root=external_root)
        result = {"run_dir": str(run_dir), **summary}
    else:
        if args.run_dir is None:
            parser.error("--stage verify requires --run-dir")
        run_dir = args.run_dir.resolve()
        if run_dir.parent != external_root or not run_dir.name.startswith(
            "raw_replay_"
        ):
            raise ContractError(
                "O4a PEM raw-replay v2 verify path is outside frozen root"
            )
        result = {"run_dir": str(run_dir), **verify_replay(root=ROOT, run_dir=run_dir)}
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
