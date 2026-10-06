"""Isolated full productive input integration, no encoder/score invocation."""

from copy import deepcopy
from pathlib import Path

import pytest

from src.dante_workflow import expanded_production as production
from src.dante_workflow.calibration_recovery import sealed, write_json, read_sealed
from src.dante_workflow.input_coverage import InputCoverageError
from tests.test_dante_workflow_expanded_context_replay import case  # noqa: F401


@pytest.fixture
def integrated(case, monkeypatch):  # noqa: F811
    c = case
    directory = c.root.parent / "preprocessing"
    directory.mkdir()
    method_path = c.root.parent / "method" / "method.json"
    method_path.parent.mkdir()
    write_json(method_path, sealed({"test": "method"}))
    reference = c.root / "reference.json"
    reference.write_text("{}")
    refs = {
        role: dict(path="reference.json", sha256=production._hash(reference))
        for role in ("protocol", "dq_reference", "scan_validity_reference")
    }
    c.parent = sealed(
        dict(
            method=dict(
                context_count=len(c.provider.allowed),
                identity_count=c.provider.identity_count,
                identity_counts=c.provider.identity_counts,
                source_hashes={},
                qualified_sources={},
                **refs,
            ),
            method_sha256=production._hash(method_path),
            source_hashes={},
            additional_runtime_source_pins={},
            runtime={"test": "stable"},
        )
    )
    write_json(directory / "binding.json", c.parent)
    c.summary = sealed(
        dict(
            status="PASS_COMPLETE_EXPANDED_CALIBRATION_PREPROCESSING_ONLY",
            binding=c.parent,
            record_count=len(c.provider.allowed),
            boundary=production.PREPROCESSING_BOUNDARY,
            all_frozen_contexts_preprocessed=True,
            population_reduced=False,
            new_dq_filter_applied=False,
        )
    )
    write_json(directory / "summary.json", c.summary)
    c.verification = sealed(
        dict(
            status="PASS_VERIFIED_EXPANDED_CALIBRATION_PREPROCESSING_ONLY",
            binding=c.parent,
            record_count=len(c.provider.allowed),
            boundary=production.PREPROCESSING_BOUNDARY,
            summary_sha256=production._hash(directory / "summary.json"),
            summary_digest=c.summary["digest"],
            verification_was_second_fetch=False,
        )
    )
    write_json(directory / "verification.json", c.verification)
    for name in ("approved.json", "preprocessing.json"):
        (c.root / name).write_text("{}")
    c.profile = dict(
        schema_version=1,
        status="ISOLATED_EXPANDED_PRODUCTIVE_INPUT_PROFILE_V1",
        source_paths=list(production.SOURCES),
        input_rule=production.INPUT_RULE,
        output_namespace="expanded_production_v1",
        automatic_resume=False,
        boundary=production.BOUNDARY,
        approved_profile_parent=dict(
            path="approved.json", sha256=production._hash(c.root / "approved.json")
        ),
        preprocessing_parent=dict(
            path="preprocessing.json",
            sha256=production._hash(c.root / "preprocessing.json"),
            source_freeze="f" * 40,
            summary_sha256=production._hash(directory / "summary.json"),
            verification_sha256=production._hash(directory / "verification.json"),
        ),
    )
    profile_path = c.root / "profile.json"
    write_json(profile_path, c.profile)
    c.args = dict(
        profile_path=profile_path,
        profile_sha=production._hash(profile_path),
        source_freeze="e" * 40,
        preprocessing_dir=directory,
        parent_args=dict(
            root=c.root,
            native_dir=c.root.parent / "native",
            method_path=method_path,
            recovery_dir=c.provider.directory,
            binding_path=c.root.parent / "native_binding.json",
            binding_sha="pin",
        ),
    )
    c.run_dir = c.root.parent / "productive"
    c.parent_calls = []

    def parent_bind(**kwargs):
        c.parent_calls.append(kwargs)
        return c.provider, c.parent

    monkeypatch.setattr(production, "preprocessing_bind", parent_bind)
    monkeypatch.setattr(production, "source_audit", lambda *a: {})
    return c


def refresh_profile(c):
    write_json(c.args["profile_path"], c.profile)
    c.args["profile_sha"] = production._hash(c.args["profile_path"])


def execute(c, stage="bind", expected_sha=None):
    return production.execute(
        stage=stage, run_dir=c.run_dir, binding_kwargs=c.args, expected_sha=expected_sha
    )


def test_full_input_binding_and_unchanged_reader(integrated):
    c = integrated
    provider, result = production.bind(**c.args)
    assert result["identity_count"] == 3 and result["context_count"] == 2
    assert result["boundary"] == production.BOUNDARY
    for detector, start, end in sorted(provider.allowed):
        context = provider.read(detector=detector, start=start, end=end)
        assert len(context.series) == 16
    assert c.calls == sorted(provider.allowed)
    assert (
        c.parent_calls[0]["source_freeze"]
        == c.profile["preprocessing_parent"]["source_freeze"]
    )
    assert not (c.run_dir / "preflight.json").exists()


def test_standalone_rebind_exact_and_preserve_preflight(integrated):
    c = integrated
    result = execute(c)
    data = (c.run_dir / "preflight.json").read_bytes()
    verified = execute(c, "verify", production._hash(c.run_dir / "preflight.json"))
    assert verified["binding"] == result
    assert read_sealed(c.run_dir / "verification.json") == verified
    assert (c.run_dir / "preflight.json").read_bytes() == data
    assert not (c.run_dir / "controller.lock").exists()
    with pytest.raises(InputCoverageError, match="already exists"):
        execute(c, "verify", production._hash(c.run_dir / "preflight.json"))
    with pytest.raises(FileExistsError):
        execute(c)


@pytest.mark.parametrize(
    "fault", ["version", "bool", "rule", "namespace", "resume", "boundary", "sources"]
)
def test_changed_profile_rejected(integrated, fault):
    c = integrated
    c.profile = deepcopy(c.profile)
    if fault == "version":
        c.profile["schema_version"] = 2
    elif fault == "bool":
        c.profile["schema_version"] = True
    elif fault == "rule":
        c.profile["input_rule"] = "fallback"
    elif fault == "namespace":
        c.profile["output_namespace"] = "legacy"
    elif fault == "resume":
        c.profile["automatic_resume"] = True
    elif fault == "boundary":
        c.profile["boundary"]["default_provider_replaced"] = 0
    else:
        c.profile["source_paths"] = []
    refresh_profile(c)
    with pytest.raises(InputCoverageError):
        production.bind(**c.args)


@pytest.mark.parametrize(
    "fault",
    [
        "summary_status",
        "verify_status",
        "count",
        "identity",
        "population",
        "dq",
        "binding",
        "digest",
        "second_fetch",
        "runtime",
    ],
)
def test_full_verified_prerequisite_rejected(integrated, fault):
    c = integrated
    s = deepcopy(c.summary)
    v = deepcopy(c.verification)
    if fault == "summary_status":
        s["status"] = "partial"
    elif fault == "verify_status":
        v["status"] = "interrupted"
    elif fault == "count":
        v["record_count"] -= 1
    elif fault == "identity":
        c.provider.identity_count -= 1
    elif fault == "population":
        s["population_reduced"] = True
    elif fault == "dq":
        s["new_dq_filter_applied"] = True
    elif fault == "binding":
        v["binding"]["extra"] = True
    elif fault == "digest":
        v["summary_digest"] = "0" * 64
    elif fault == "second_fetch":
        v["verification_was_second_fetch"] = True
    else:
        c.parent = sealed({**c.parent, "runtime": {"test": "changed"}})
    s.pop("digest")
    v.pop("digest")
    write_json(c.args["preprocessing_dir"] / "summary.json", sealed(s))
    if fault != "digest":
        v["summary_digest"] = read_sealed(c.args["preprocessing_dir"] / "summary.json")[
            "digest"
        ]
    v["summary_sha256"] = production._hash(c.args["preprocessing_dir"] / "summary.json")
    write_json(c.args["preprocessing_dir"] / "verification.json", sealed(v))
    ref = c.profile["preprocessing_parent"]
    ref["summary_sha256"] = production._hash(
        c.args["preprocessing_dir"] / "summary.json"
    )
    ref["verification_sha256"] = production._hash(
        c.args["preprocessing_dir"] / "verification.json"
    )
    refresh_profile(c)
    with pytest.raises(InputCoverageError):
        production.bind(**c.args)


@pytest.mark.parametrize("name", ["summary.json", "verification.json", "binding.json"])
def test_per_read_changed_parent_stops_before_reader(integrated, name):
    c = integrated
    provider, _ = production.bind(**c.args)
    (c.args["preprocessing_dir"] / name).write_text("changed")
    with pytest.raises(InputCoverageError):
        provider.read(detector="H1", start=100.25, end=104.25)
    assert c.calls == []


def test_parent_change_during_read_rejected(integrated, monkeypatch):
    c = integrated
    provider, _ = production.bind(**c.args)
    original = c.provider.read

    def changed(**kwargs):
        result = original(**kwargs)
        (c.args["preprocessing_dir"] / "summary.json").write_text("changed")
        return result

    monkeypatch.setattr(c.provider, "read", changed)
    with pytest.raises(InputCoverageError):
        provider.read(detector="H1", start=100.25, end=104.25)


@pytest.mark.parametrize(
    "parent", ["root", "recovery_dir", "native_dir", "method_path", "preprocessing"]
)
def test_preserved_output_isolation(integrated, parent):
    c = integrated
    if parent == "preprocessing":
        target = c.args["preprocessing_dir"]
    else:
        target = c.args["parent_args"][parent]
    c.run_dir = target.parent if parent == "method_path" else target
    with pytest.raises(InputCoverageError):
        execute(c)


def test_live_parent_or_output_lock_rejected(integrated):
    c = integrated
    execute(c)
    (c.run_dir / "controller.lock").write_text("another writer")
    with pytest.raises(InputCoverageError):
        execute(c, "verify", production._hash(c.run_dir / "preflight.json"))
    assert (c.run_dir / "controller.lock").read_text() == "another writer"
    (c.args["preprocessing_dir"] / "controller.lock").write_text("parent writer")
    with pytest.raises(InputCoverageError):
        production.bind(**c.args)


def test_changed_standalone_evidence_rejected(integrated):
    c = integrated
    execute(c)
    with pytest.raises(InputCoverageError):
        execute(c, "verify", "0" * 64)
    assert not (c.run_dir / "verification.json").exists()


def test_source_freeze_required():
    with pytest.raises(InputCoverageError):
        production.source_audit(Path.cwd(), "HEAD")


def test_cli_requires_expected_pin_before_binding():
    argv = ["--stage", "verify"]
    for key in (
        "repository-root",
        "profile",
        "recovery-dir",
        "native-dir",
        "binding",
        "method",
        "preprocessing-dir",
        "run-dir",
        "profile-sha256",
        "source-freeze",
        "binding-sha256",
    ):
        argv.extend(["--" + key, "test"])
    with pytest.raises(SystemExit):
        production.main(argv)


def test_failed_writer_preserves_evidence_and_disallows_restart(
    integrated, monkeypatch
):
    c = integrated
    provider, result = production.bind(**c.args)
    monkeypatch.setattr(production, "bind", lambda **kw: (provider, result))
    monkeypatch.setattr(
        provider,
        "guard",
        lambda: (_ for _ in ()).throw(InputCoverageError("changed parent")),
    )
    with pytest.raises(InputCoverageError):
        execute(c)
    failure = read_sealed(c.run_dir / "failure.json")
    assert failure["automatic_resume"] is False
    assert not (c.run_dir / "controller.lock").exists()
    with pytest.raises(FileExistsError):
        execute(c)
    assert read_sealed(c.run_dir / "failure.json") == failure


def test_protocol_reference_rehashed_per_read(integrated):
    c = integrated
    provider, _ = production.bind(**c.args)
    (c.root / "reference.json").write_text("changed")
    with pytest.raises(InputCoverageError):
        provider.read(detector="H1", start=100.25, end=104.25)
    assert c.calls == []
