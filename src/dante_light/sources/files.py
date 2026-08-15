"""Immutable manifest-backed finite replay source."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, WindowIdentity
from src.dante_light.executor import WindowTask


class ReplayManifestSource:
    def __init__(self, manifest_path: str | Path, *, root: str | Path):
        self.root = Path(root)
        self.manifest_path = Path(manifest_path)
        self.header = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        entries_path = self.root / self.header["entries_path"]
        if sha256_file(entries_path) != self.header["entries_file_sha256"]:
            raise ContractError("DANTE-Light replay entry-file SHA256 mismatch")
        self.entries = [
            json.loads(line)
            for line in entries_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def tasks(
        self, *, roles: set[str] | None = None, limit: int | None = None
    ) -> list[WindowTask]:
        selected = [
            entry
            for entry in self.entries
            if not roles or roles.intersection(entry["roles"])
        ]
        grouped: dict[str, dict[str, Any]] = {}
        for entry in selected:
            window = WindowIdentity.from_dict(entry["window"])
            value = grouped.setdefault(
                window.window_id,
                {"window": window, "cases": [], "roles": set()},
            )
            if value["window"] != window:
                raise ContractError(f"Conflicting replay identity {window.window_id}")
            value["cases"].append(entry)
            value["roles"].update(entry["roles"])
        tasks = [
            WindowTask(
                value["window"],
                {
                    "case_ids": sorted(
                        entry["case_id"] for entry in value["cases"]
                    ),
                    "roles": sorted(value["roles"]),
                    "expected": [
                        entry.get("expected", {}) for entry in value["cases"]
                    ],
                },
            )
            for value in grouped.values()
        ]
        tasks.sort(key=lambda task: (task.window.detector, task.window.gps_start))
        if limit is not None:
            if limit <= 0:
                raise ValueError("limit must be positive")
            tasks = tasks[:limit]
        return tasks
