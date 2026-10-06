"""Explicit native immutable-input scan scheduling; scientific hashing unchanged."""

from contextlib import contextmanager
import os
from pathlib import Path
import stat


def verify_immutable_directory(directory):
    """Require kernel read-only view and root-owned, non-writable backing bytes."""
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("immutable scan directory must be a real directory")
    if not os.statvfs(directory).f_flag & os.ST_RDONLY:
        raise ValueError("immutable scan directory is not mounted read-only")
    count = 0
    for base, dirs, files in os.walk(directory, followlinks=False):
        for path in (Path(base), *(Path(base) / p for p in dirs + files)):
            mode = path.lstat()
            if (
                stat.S_ISLNK(mode.st_mode)
                or mode.st_uid != 0
                or mode.st_mode & 0o222
                or not (stat.S_ISDIR(mode.st_mode) or stat.S_ISREG(mode.st_mode))
            ):
                raise ValueError("mutable or indirect immutable scan backing entry")
            count += 1
    return count


class ImmutableScanScope:
    """Only declared immutable parents may skip repeated directory enumerations."""

    def __init__(self, full_scan, directories):
        self.full_scan = full_scan
        self.directories = tuple(Path(p).resolve() for p in directories)
        if not self.directories or len(set(self.directories)) != len(self.directories):
            raise ValueError("unique immutable scan directories required")
        self.ready = False
        self.initial_scans = 0
        self.final_scans = 0
        self.repeated_scans_avoided = 0
        self.backing_entries_checked = 0

    def start(self):
        for directory in self.directories:
            self.backing_entries_checked += verify_immutable_directory(directory)
            self.full_scan(directory)
            self.initial_scans += 1
        self.ready = True

    def __call__(self, directory):
        directory = Path(directory).resolve()
        if not self.ready or directory not in self.directories:
            return self.full_scan(directory)
        # Keep the original active/failure marker checks even in the ro scope.
        if any((directory / p).exists() for p in ("controller.lock", "failure.json")):
            return self.full_scan(directory)
        self.repeated_scans_avoided += 1
        return None

    def finish(self):
        self.ready = False
        for directory in self.directories:
            verify_immutable_directory(directory)
            self.full_scan(directory)
            self.final_scans += 1

    def evidence(self):
        return dict(
            policy="EXPLICIT_IMMUTABLE_PARENT_INITIAL_FINAL_FULL_SCAN_V1",
            protected_directories=[str(p) for p in self.directories],
            initial_full_scans=self.initial_scans,
            final_full_scans=self.final_scans,
            repeated_full_scans_avoided=self.repeated_scans_avoided,
            immutable_backing_entries_checked=self.backing_entries_checked,
            per_read_hashing_replaced=False,
            numerical_algorithm_replaced=False,
            numerical_tolerance_changed=False,
        )


@contextmanager
def calibration_scan_scope(directories):
    """Explicit dispatch only at the two frozen calibration parent scan sites."""
    from src.dante_workflow import expanded_calibration, expanded_production
    from src.dante_workflow.expanded_context_replay import quiet

    modules = (expanded_calibration, expanded_production)
    if any(m.quiet is not quiet for m in modules):
        raise ValueError("unsupported or already replaced calibration scan dispatch")
    scope = ImmutableScanScope(quiet, directories)
    scope.start()
    for module in modules:
        module.quiet = scope
    try:
        yield scope
    finally:
        # Always restore original functions, including interrupted/failed stages.
        try:
            scope.finish()
        finally:
            for module in modules:
                module.quiet = quiet
