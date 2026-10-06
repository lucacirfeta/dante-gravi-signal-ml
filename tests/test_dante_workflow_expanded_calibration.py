"""Fresh calibration contracts/whole-population dispatch; real parents untouched."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.dante_workflow import expanded_calibration as cal
from src.dante_workflow.calibration_recovery import read_sealed, sealed, write_json
from src.dante_light.o4a_corrected_protocol import _digest_rows


def ledger():
    return [
        dict(
            session_id=s,
            detector=d,
            catalog_gps_start=g,
            analysis_gps_start=g + 4,
            required_padded_interval=[g, g + 40],
            replay_disposition="REQUIRE_EXACT_REPLAY",
            historical_score_float32_hex=np.float32(0.25).tobytes().hex(),
        )
        for s, d, g in [(1, "H1", 100.0), (2, "H1", 100.0), (1, "L1", 110.0)]
    ]


def protocol(rows):
    digest, n = _digest_rows(rows)
    return dict(
        representation=dict(whitening_pad_s=4.0, analysis_duration_s=32.0),
        execution_parameters=dict(
            primary_calibration=dict(workers=1, batch_size=2, device="cuda")
        ),
        calibration_population=dict(
            identity_jsonl_sha256=digest,
            identity_count=n,
            replay_disposition_counts={
                "H1/REQUIRE_EXACT_REPLAY": 2,
                "L1/REQUIRE_EXACT_REPLAY": 1,
            },
            session_detector_counts={"H1": 2, "L1": 1},
            source_hdf5_references=[],
            recalibration=dict(estimator="numpy.percentile(scores, 99.0)"),
        ),
    )


def test_memberships_not_deduplicated():
    rows = ledger()
    groups = cal.population(
        rows, protocol(rows), {("H1", 100.0, 140.0), ("L1", 110.0, 150.0)}
    )
    assert len(groups) == 3 and sum(map(len, groups.values())) == 3


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "missing",
        "context",
        "geometry",
        "scope",
        "sessions",
        "digest",
        "replay_count",
    ],
)
def test_population_drift(mutation):
    rows = ledger()
    p = protocol(rows)
    allowed = {("H1", 100.0, 140.0), ("L1", 110.0, 150.0)}
    if mutation == "duplicate":
        rows[1] = deepcopy(rows[0])
    if mutation == "missing":
        rows.pop()
    if mutation == "context":
        allowed.remove(("L1", 110.0, 150.0))
    if mutation == "geometry":
        rows[0]["analysis_gps_start"] += 1
    if mutation == "scope":
        rows[0]["replay_disposition"] = "UNAPPROVED"
    if mutation == "sessions":
        p["calibration_population"]["session_detector_counts"]["H1"] += 1
    if mutation == "digest":
        p["calibration_population"]["identity_jsonl_sha256"] = "0" * 64
    if mutation == "replay_count":
        p["calibration_population"]["replay_disposition_counts"][
            "H1/REQUIRE_EXACT_REPLAY"
        ] += 1
    # Exercise deeper checks after an otherwise correctly sealed changed ledger.
    if mutation in ("duplicate", "geometry", "scope"):
        p["calibration_population"]["identity_jsonl_sha256"] = _digest_rows(rows)[0]
    with pytest.raises(cal.InputCoverageError):
        cal.population(rows, p, allowed)


def test_percentile_from_versioned_estimator():
    scores = [0.2, 0.5, 0.6]
    assert cal.percentile(scores, "numpy.percentile(scores, 99.0)") == float(
        np.percentile(np.asarray(scores, dtype=np.float64), 99.0)
    )
    assert cal.percentile(scores, "numpy.percentile(scores, 50.0)") == 0.5


@pytest.mark.parametrize(
    "scores,estimator",
    [
        ([], "numpy.percentile(scores, 99.0)"),
        ([np.nan], "numpy.percentile(scores, 99.0)"),
        ([[1]], "numpy.percentile(scores, 99.0)"),
        ([1], "eval(scores)"),
        ([1], "numpy.percentile(scores, 101)"),
        ([1], "numpy.percentile(scores, 99, method='nearest')"),
    ],
)
def test_invalid_threshold_contract(scores, estimator):
    with pytest.raises(cal.InputCoverageError):
        cal.percentile(scores, estimator)


def test_historical_comparison_only_scope():
    row = ledger()[0]
    cal.historical_check(row, 0.25, 2e-7)
    with pytest.raises(cal.InputCoverageError):
        cal.historical_check(row, 0.4, 2e-7)
    row["replay_disposition"] = "CORRECTED_CONTEXT_NO_REPLAY"
    cal.historical_check(row, 0.4, 2e-7)


class FakeEngine:
    runtime = {"test": "stable"}
    qualification = {"test": "driver_recorded"}
    provenance = {"test": "model"}
    tolerance = {"score_atol": 2e-7, "score_rtol": 0.0}

    def __init__(self, *args):
        self.calls = []
        self.drift = False

    def guard(self):
        if self.drift:
            raise cal.InputCoverageError("runtime changed")

    def score(self, images):
        self.guard()
        self.calls.append(len(images))
        return [
            dict(
                score=0.25,
                token_sha256="a" * 64,
                token_shape=[2, 3],
                oracle_score=0.25,
                absolute_error=0.0,
            )
            for _ in images
        ]


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    rows = ledger()
    p = protocol(rows)
    allowed = {("H1", 100.0, 140.0), ("L1", 110.0, 150.0)}
    parents = [
        tmp_path / name for name in ("productive", "preprocessing", "native", "method")
    ]
    for path in parents:
        path.mkdir()
    provider = SimpleNamespace(
        allowed=allowed, delegate=SimpleNamespace(), guard=lambda: None
    )
    state = dict(
        root=tmp_path,
        provider=provider,
        groups=cal.population(rows, p, allowed),
        protocol=p,
        engine=FakeEngine(),
        pins={},
        productive_dir=parents[0],
        preprocessing_dir=parents[1],
        contract={},
        binding=sealed(
            dict(identity_count=3, context_count=2, productive={"test": "parent"})
        ),
    )
    kwargs = dict(
        productive_kwargs=dict(
            parent_args=dict(
                native_dir=parents[2], method_path=parents[3] / "method.json"
            )
        ),
        source_freeze="a" * 40,
    )
    stages = []
    monkeypatch.setattr(cal, "prepare", lambda **_: state)
    monkeypatch.setattr(cal, "isolated", lambda path, _: Path(path))
    monkeypatch.setattr(
        cal, "productive_bind", lambda **_: (provider, state["binding"]["productive"])
    )
    monkeypatch.setattr(cal, "source_audit", lambda *_: {})

    def images(s, batch, stage, pool):
        stages.append(stage)
        return [np.zeros((2, 2, 3), dtype=np.uint8) for _ in batch], [
            dict(native={"test": "native"}, image_sha256="b" * 64) for _ in batch
        ]

    monkeypatch.setattr(cal, "images", images)
    return SimpleNamespace(
        state=state, kwargs=kwargs, stages=stages, directory=tmp_path / "fresh"
    )


def test_fresh_run_standalone_full_replay(prepared):
    c = prepared
    run = cal.execute(stage="run", run_dir=c.directory, prepare_kwargs=c.kwargs)
    assert (
        run["identity_count"] == 3
        and run["context_count"] == 2
        and len(run["sessions"]) == 3
    )
    assert set(c.stages) == {"run"}
    verify = cal.execute(
        stage="verify",
        run_dir=c.directory,
        prepare_kwargs=c.kwargs,
        summary_sha=cal._hash(c.directory / "summary.json"),
    )
    assert verify["status"] == "PASS_VERIFIED_ISOLATED_EXPANDED_CALIBRATION_ONLY"
    assert (
        set(c.stages) == {"run", "verify"}
        and not (c.directory / "controller.lock").exists()
    )
    assert cal.read_sealed(c.directory / "summary.json") == run
    with pytest.raises(cal.InputCoverageError, match="already exists"):
        cal.execute(
            stage="verify",
            run_dir=c.directory,
            prepare_kwargs=c.kwargs,
            summary_sha=cal._hash(c.directory / "summary.json"),
        )
    with pytest.raises(FileExistsError):
        cal.execute(stage="run", run_dir=c.directory, prepare_kwargs=c.kwargs)


@pytest.mark.parametrize(
    "mutation", ["shard", "extra", "binding", "runtime", "summarypin", "lock"]
)
def test_verifier_drift_preserves_failure(prepared, mutation):
    c = prepared
    cal.execute(stage="run", run_dir=c.directory, prepare_kwargs=c.kwargs)
    sha = cal._hash(c.directory / "summary.json")
    if mutation == "shard":
        path = c.directory / "sessions" / "1_H1.json"
        r = read_sealed(path)
        r.pop("digest")
        r["empirical_p99"] += 0.01
        write_json(path, sealed(r))
    if mutation == "extra":
        (c.directory / "sessions" / "extra.json").write_text("{}")
    if mutation == "binding":
        write_json(c.directory / "binding.json", sealed({"wrong": "parent"}))
    if mutation == "runtime":
        c.state["engine"].drift = True
    if mutation == "summarypin":
        sha = "0" * 64
    if mutation == "lock":
        (c.directory / "controller.lock").write_text("{}")
    with pytest.raises((cal.InputCoverageError, ValueError)):
        cal.execute(
            stage="verify",
            run_dir=c.directory,
            prepare_kwargs=c.kwargs,
            summary_sha=sha,
        )
    assert not (c.directory / "verification.json").exists()
    assert (c.directory / "summary.json").exists()
    if mutation in ("shard", "extra", "runtime"):
        assert read_sealed(c.directory / "failure.json")["automatic_resume"] is False
    if mutation == "lock":
        assert (c.directory / "controller.lock").exists()


@pytest.mark.parametrize(
    "parent", ["productive_dir", "preprocessing_dir", "native", "method"]
)
def test_output_parent_isolation(prepared, parent):
    c = prepared
    target = c.state.get(parent)
    if target is None:
        target = Path(
            c.kwargs["productive_kwargs"]["parent_args"][
                "native_dir" if parent == "native" else "method_path"
            ]
        )
        if parent == "method":
            target = target.parent
    with pytest.raises(cal.InputCoverageError, match="overlaps"):
        cal.execute(stage="run", run_dir=target / "wrong", prepare_kwargs=c.kwargs)


def test_short_score_batch_fails_closed(prepared, monkeypatch):
    c = prepared
    monkeypatch.setattr(c.state["engine"], "score", lambda _: [])
    with pytest.raises(cal.InputCoverageError, match="cardinality"):
        cal.execute(stage="run", run_dir=c.directory, prepare_kwargs=c.kwargs)
    assert read_sealed(c.directory / "failure.json")["stage"] == "run"
    assert not (c.directory / "controller.lock").exists()
    assert not (c.directory / "summary.json").exists()


def test_cli_requires_summary_before_prepare(monkeypatch, tmp_path):
    monkeypatch.setattr(cal, "prepare", lambda **_: pytest.fail("must not bind"))
    args = ["--stage", "verify"]
    for name in (
        "repository-root",
        "contract",
        "profile",
        "productive-dir",
        "recovery-dir",
        "native-dir",
        "binding",
        "method",
        "preprocessing-dir",
        "run-dir",
    ):
        args.extend(["--" + name, str(tmp_path / name)])
    for name in (
        "contract-sha256",
        "source-freeze",
        "profile-sha256",
        "productive-source-freeze",
        "binding-sha256",
    ):
        args.extend(["--" + name, "a" * 64])
    with pytest.raises(SystemExit):
        cal.main(args)


@pytest.mark.parametrize(
    "change", ["version", "bool", "scope", "resume", "rule", "boundary"]
)
def test_contract_fail_closed(tmp_path, change):
    c = json.loads(
        (
            Path(__file__).parents[1]
            / "config/dante_workflow_expanded_calibration_v1.json"
        ).read_text()
    )
    if change == "version":
        c["schema_version"] = 2
    if change == "bool":
        c["schema_version"] = True
    if change == "scope":
        c["boundary"]["o4b_launch_allowed"] = True
    if change == "resume":
        c["automatic_resume"] = True
    if change == "rule":
        c["same_runtime_replay_rule"] = "tolerance waiver"
    if change == "boundary":
        c["boundary"]["default_provider_replaced"] = 0
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(c))
    with pytest.raises(cal.InputCoverageError):
        cal.load_contract(path, cal._hash(path))


@pytest.mark.parametrize("freeze", [None, "main", "0" * 39, "Z" * 40])
def test_source_freeze_required(tmp_path, freeze):
    with pytest.raises(cal.InputCoverageError):
        cal.source_audit(tmp_path, freeze)


@pytest.fixture
def binding_case(tmp_path, monkeypatch):
    from src.dante_light import o4a_corrected_protocol as module

    root = tmp_path / "repo"
    root.mkdir()
    directory = tmp_path / "productive"
    directory.mkdir()
    rows = ledger()
    p = protocol(rows)
    c = json.loads(
        (
            Path(__file__).parents[1]
            / "config/dante_workflow_expanded_calibration_v1.json"
        ).read_text()
    )
    policy = json.loads(
        (
            Path(__file__).parents[1] / "config/dante_workflow_scoring_replay_v1.json"
        ).read_text()
    )
    for name in c["scientific_source_pins"]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test source")
        c["scientific_source_pins"][name] = cal._hash(path)
    for role in (
        "protocol_parent",
        "runtime_parent",
        "tolerance_parent",
        "artifact_manifest",
    ):
        path = root / (role + ".json")
        path.write_text(json.dumps(p if role == "protocol_parent" else {}))
        policy[role] = dict(path=path.name, sha256=cal._hash(path))
    policy_path = root / "policy.json"
    policy_path.write_text(json.dumps(policy))
    c["qualification_policy"] = dict(
        path=policy_path.name, sha256=cal._hash(policy_path)
    )
    productive = sealed(
        dict(
            context_count=2,
            identity_count=3,
            boundary={"test": False},
            preprocessing_binding=dict(
                method=dict(
                    representation=p["representation"],
                    execution_parameters=p["execution_parameters"][
                        "primary_calibration"
                    ],
                )
            ),
        )
    )
    write_json(directory / "preflight.json", productive)
    c["productive_parent"]["preflight_sha256"] = cal._hash(directory / "preflight.json")
    verified = sealed(
        dict(
            status="PASS_VERIFIED_ISOLATED_EXPANDED_PRODUCTIVE_INPUT_BINDING_ONLY",
            preflight_sha256=c["productive_parent"]["preflight_sha256"],
            preflight_digest=productive["digest"],
            binding=productive,
            context_count=2,
            identity_count=3,
            boundary=productive["boundary"],
        )
    )
    write_json(directory / "verification.json", verified)
    c["productive_parent"]["verification_sha256"] = cal._hash(
        directory / "verification.json"
    )
    path = root / "contract.json"
    provider = SimpleNamespace(
        allowed={("H1", 100.0, 140.0), ("L1", 110.0, 150.0)}, guard=lambda: None
    )
    monkeypatch.setattr(cal, "source_audit", lambda *_: {})
    monkeypatch.setattr(cal, "productive_bind", lambda **_: (provider, productive))
    monkeypatch.setattr(module, "iter_calibration_identities", lambda _: iter(rows))
    monkeypatch.setattr(cal, "Engine", FakeEngine)
    kwargs = dict(
        contract_path=path,
        source_freeze="a" * 40,
        productive_dir=directory,
        productive_kwargs=dict(
            parent_args=dict(root=root),
            profile_sha=c["productive_parent"]["profile_sha256"],
            source_freeze=c["productive_parent"]["source_freeze"],
            preprocessing_dir=tmp_path / "preprocessing",
        ),
    )

    def run():
        path.write_text(json.dumps(c))
        kwargs["contract_sha"] = cal._hash(path)
        return cal.prepare(**kwargs)

    return SimpleNamespace(
        root=root,
        c=c,
        productive=productive,
        verified=verified,
        rows=rows,
        kwargs=kwargs,
        run=run,
        directory=directory,
    )


def test_positive_full_binding_wiring(binding_case):
    c = binding_case
    state = c.run()
    assert (
        state["binding"]["identity_count"] == 3
        and state["binding"]["context_count"] == 2
    )
    assert state["binding"]["session_detector_count"] == 3
    cal.guard(state)
    path = next(path for path in state["pins"] if path.name == "policy.json")
    path.write_text("mutated")
    with pytest.raises(ValueError):
        cal.guard(state)


@pytest.mark.parametrize(
    "mutation",
    [
        "status",
        "count",
        "seal",
        "source",
        "inventory",
        "population",
        "profile",
        "geometry",
    ],
)
def test_full_binding_prerequisite_drift(binding_case, mutation):
    c = binding_case
    if mutation in ("status", "count", "seal"):
        v = deepcopy(c.verified)
        v.pop("digest")
        if mutation == "status":
            v["status"] = "PENDING"
        if mutation == "count":
            v["identity_count"] += 1
        write_json(c.directory / "verification.json", sealed(v))
        if mutation == "seal":
            (c.directory / "verification.json").write_text("{}")
        c.c["productive_parent"]["verification_sha256"] = cal._hash(
            c.directory / "verification.json"
        )
    if mutation == "source":
        next(iter(c.c["scientific_source_pins"].values()))
        (c.root / "config.yaml").write_text("changed")
    if mutation == "inventory":
        c.c["scientific_source_pins"].pop("config.yaml")
    if mutation == "population":
        c.rows.pop()
    if mutation == "profile":
        c.kwargs["productive_kwargs"]["profile_sha"] = "0" * 64
    if mutation == "geometry":
        c.productive["preprocessing_binding"]["method"]["representation"][
            "whitening_pad_s"
        ] = 5
    with pytest.raises((ValueError, cal.InputCoverageError)):
        c.run()


@pytest.mark.parametrize("stage", ["run", "verify"])
@pytest.mark.parametrize("mutation", [None, "image", "native", "pin", "label"])
def test_fresh_image_dispatch_and_guards(tmp_path, monkeypatch, stage, mutation):
    rep = dict(sample_rate_hz=4096, image_shape=[2, 2, 3], analysis_duration_s=32.0)
    row = ledger()[0]
    key = ("H1", 100.0, 140.0)
    image = np.zeros((2, 2, 3), dtype=np.uint8)
    directory = tmp_path / "preprocessing"
    (directory / "images").mkdir(parents=True)
    (directory / "contexts").mkdir()
    receipt_path, image_path = cal.paths(directory, key)
    np.save(image_path, image, allow_pickle=False)
    proof = {"native": "unchanged"}
    write_json(
        receipt_path,
        sealed(
            dict(
                native_context=proof,
                image_file_sha256=cal._hash(image_path),
                image_values_sha256=__import__("hashlib")
                .sha256(image.tobytes())
                .hexdigest(),
            )
        ),
    )
    delegate = SimpleNamespace(expected_names={key: "H1:STRAIN"})
    series = SimpleNamespace(value=np.ones(5), name="H1:STRAIN")
    provider = SimpleNamespace(
        delegate=delegate,
        read=lambda **_: SimpleNamespace(series=series),
        guard=lambda: None,
    )
    state = dict(
        provider=provider,
        protocol=dict(representation=rep),
        preprocessing_dir=directory,
        pins={},
        productive_dir=tmp_path / "productive",
    )
    state["productive_dir"].mkdir()
    changed = image.copy()
    if mutation == "image":
        changed[0, 0, 0] = 1
    if mutation == "pin":
        image_path.write_bytes(b"changed")
    monkeypatch.setattr(
        cal,
        "record",
        lambda *_: {"native": "changed"} if mutation == "native" else proof,
    )
    monkeypatch.setattr(cal, "independent_values", lambda *_: series.value)
    monkeypatch.setattr(cal, "independent_image", lambda *_: changed)
    pool = SimpleNamespace(
        submit=lambda *_: SimpleNamespace(
            result=lambda: (105 if mutation == "label" else 104, changed)
        )
    )
    if mutation is None or (mutation == "label" and stage == "verify"):
        output, proofs = cal.images(state, [row], stage, pool)
        assert np.array_equal(output[0], image) and proofs[0]["native"] == proof
    else:
        with pytest.raises((ValueError, cal.InputCoverageError)):
            cal.images(state, [row], stage, pool)
