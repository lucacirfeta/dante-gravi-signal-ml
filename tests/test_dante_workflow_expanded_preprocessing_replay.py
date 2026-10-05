"""Full-domain dispatch/storage/parity tests; no scores or historical output reuse."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.dante_workflow import expanded_preprocessing_replay as replay
from src.dante_workflow.calibration_recovery import sealed, read_sealed, write_json
from src.dante_workflow.input_coverage import InputCoverageError
from tests.test_dante_workflow_expanded_context_replay import case  # noqa: F401


class InlinePool:
    """Only dispatch infrastructure mocked; real retained-container reader used."""

    def __init__(self, **kwargs):
        self.settings = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def submit(self, fn, *args):
        return SimpleNamespace(result=lambda: fn(*args))


def synthetic_worker(values, t0, dt, name, begin, end, complete):
    assert complete is True
    assert begin == t0 + 1
    assert end == t0 + 3
    return int(begin), np.full((2, 3, 3), int(values.sum()) % 256, dtype=np.uint8)


@pytest.fixture
def prepared(case, monkeypatch):  # noqa: F811 - imported shared synthetic fixture
    c = case
    rep = dict(
        sample_rate_hz=4,
        whitening_pad_s=1,
        analysis_duration_s=2,
        image_shape=[2, 3, 3],
    )
    method = dict(
        representation=rep,
        execution_parameters=dict(workers=2, batch_size=1),
        identity_count=3,
        context_count=2,
    )
    c.binding = sealed(
        dict(method=method, boundary=replay.BOUNDARY, runtime={"synthetic": "runtime"})
    )
    monkeypatch.setattr(replay, "bind", lambda **kw: (c.provider, c.binding))
    monkeypatch.setattr(replay, "ProcessPoolExecutor", InlinePool)
    from src.core import patch_producer

    monkeypatch.setattr(patch_producer, "_worker_preprocess", synthetic_worker)
    monkeypatch.setattr(
        replay,
        "independent_image",
        lambda values, key, name, rep: synthetic_worker(
            values,
            key[1],
            1 / rep["sample_rate_hz"],
            name,
            key[1] + rep["whitening_pad_s"],
            key[2] - rep["whitening_pad_s"],
            True,
        )[1],
    )
    c.provider.expected_names = {k: k[0] for k in c.provider.allowed}
    c.run_dir = c.run_dir.parent / "preprocessing"
    return c


def run(c):
    return replay.execute(stage="run", run_dir=c.run_dir, binding_kwargs={})


def verify(c):
    return replay.execute(
        stage="verify",
        run_dir=c.run_dir,
        binding_kwargs={},
        summary_sha=replay._hash(c.run_dir / "summary.json"),
    )


def test_complete_dispatch_and_independent_verifier(prepared, monkeypatch):
    c = prepared
    summary = run(c)
    assert c.calls == sorted(c.provider.allowed)
    assert summary["record_count"] == 2
    assert summary["binding"]["method"]["identity_count"] == 3
    assert summary["boundary"] == replay.BOUNDARY
    from src.core import patch_producer

    monkeypatch.setattr(
        c.provider, "read", lambda **kw: pytest.fail("verifier must not use consumer")
    )
    monkeypatch.setattr(
        patch_producer,
        "_worker_preprocess",
        lambda *a: pytest.fail("verifier must not use worker"),
    )
    result = verify(c)
    assert result["status"] == "PASS_VERIFIED_EXPANDED_CALIBRATION_PREPROCESSING_ONLY"
    assert result["verification_was_second_fetch"] is False
    assert "SAME frozen" in result["independent_dispatch"]
    assert not (c.run_dir / "controller.lock").exists()
    with pytest.raises(InputCoverageError):
        verify(c)


@pytest.mark.parametrize(
    "fault",
    [
        "pixels",
        "npy",
        "receipt",
        "extra_image",
        "extra_receipt",
        "missing_image",
        "missing_receipt",
        "summary",
        "parent",
    ],
)
def test_independent_verification_rejects_faults(prepared, monkeypatch, fault):
    c = prepared
    run(c)
    json_path, image_path = replay.paths(c.run_dir, sorted(c.provider.allowed)[0])
    if fault == "pixels":
        image = np.load(image_path)
        image[0, 0, 0] ^= 1
        with image_path.open("wb") as stream:
            np.save(stream, image, allow_pickle=False)
        row = read_sealed(json_path)
        row["image_file_sha256"] = replay._hash(image_path)
        row["image_values_sha256"] = replay.hashlib.sha256(image.tobytes()).hexdigest()
        write_json(json_path, sealed({k: v for k, v in row.items() if k != "digest"}))
    elif fault == "npy":
        image_path.write_bytes(b"damaged")
    elif fault == "receipt":
        json_path.write_text("{}")
    elif fault == "extra_image":
        (c.run_dir / "images" / "extra.npy").write_bytes(b"extra")
    elif fault == "extra_receipt":
        (c.run_dir / "contexts" / "extra.json").write_text("{}")
    elif fault == "missing_image":
        image_path.unlink()
    elif fault == "missing_receipt":
        json_path.unlink()
    elif fault == "summary":
        summary = read_sealed(c.run_dir / "summary.json")
        summary["record_count"] += 1
        write_json(
            c.run_dir / "summary.json",
            sealed({k: v for k, v in summary.items() if k != "digest"}),
        )
    else:
        different = deepcopy(c.binding)
        different["runtime"] = {"changed": True}
        monkeypatch.setattr(replay, "bind", lambda **kw: (c.provider, different))
    with pytest.raises((ValueError, FileNotFoundError)):
        verify(c)
    assert not (c.run_dir / "verification.json").exists()
    assert (c.run_dir / "summary.json").exists()


@pytest.mark.parametrize("fault", ["missing", "dtype", "shape", "label", "exception"])
def test_worker_failure_stops_without_skip(prepared, monkeypatch, fault):
    from src.core import patch_producer

    def worker(*args):
        if fault == "exception":
            raise RuntimeError("failure")
        gps, image = synthetic_worker(*args)
        return {
            "missing": (gps, None),
            "dtype": (gps, image.astype(float)),
            "shape": (gps, image[:1]),
            "label": (gps + 1, image),
        }[fault]

    monkeypatch.setattr(patch_producer, "_worker_preprocess", worker)
    with pytest.raises((InputCoverageError, RuntimeError)):
        run(prepared)
    assert read_sealed(prepared.run_dir / "failure.json")["automatic_resume"] is False
    assert not (prepared.run_dir / "summary.json").exists()
    assert not (prepared.run_dir / "controller.lock").exists()


def test_active_lock_and_duplicate_run_preserved(prepared):
    run(prepared)
    with pytest.raises(FileExistsError):
        run(prepared)
    lock = prepared.run_dir / "controller.lock"
    lock.write_text("other-controller")
    with pytest.raises(InputCoverageError):
        verify(prepared)
    assert lock.read_text() == "other-controller"


def test_real_component_chain_exact_worker_parity():
    from src.core.patch_producer import _worker_preprocess
    from src.core.utils import load_config

    root = Path(__file__).resolve().parents[1]
    protocol = json.loads(
        (root / "config/dante_o4a_corrected_protocol_v4.json").read_text()
    )
    rep = protocol["representation"]
    begin = 100.25
    end = begin + rep["analysis_duration_s"] + 2 * rep["whitening_pad_s"]
    key = ("H1", begin, end)
    rng = np.random.default_rng(2026)
    values = rng.normal(0, 1e-21, int((end - begin) * rep["sample_rate_hz"]))
    gps, image = _worker_preprocess(
        values,
        begin,
        1 / rep["sample_rate_hz"],
        "H1",
        begin + rep["whitening_pad_s"],
        end - rep["whitening_pad_s"],
        True,
    )
    assert gps == int(begin + rep["whitening_pad_s"])
    assert load_config()["preprocessing"]["qrange"] == rep["query_qrange"]
    rebuilt = replay.independent_image(values, key, "H1", rep)
    assert np.array_equal(image, rebuilt)


def test_contract_exact_boundaries():
    root = Path(__file__).resolve().parents[1]
    contract = json.loads(
        (
            root / "config/dante_workflow_expanded_preprocessing_replay_v1.json"
        ).read_text()
    )
    assert contract["boundary"] == replay.BOUNDARY
    assert contract["measurement_rule"] == replay.MEASUREMENT
    assert contract["population_rule"] == replay.POPULATION
    assert contract["image_storage_rule"] == replay.STORAGE
    assert contract["automatic_resume"] is False
    for name, sha in contract["additional_runtime_source_pins"].items():
        assert replay._hash(root / name) == sha


def test_actual_spawn_worker_dispatch_matches_chain():
    from src.core.patch_producer import _worker_preprocess

    root = Path(__file__).resolve().parents[1]
    rep = json.loads(
        (root / "config/dante_o4a_corrected_protocol_v4.json").read_text()
    )["representation"]
    start = 200.25
    end = start + rep["analysis_duration_s"] + 2 * rep["whitening_pad_s"]
    values = np.random.default_rng(2027).normal(
        0, 1e-21, int((end - start) * rep["sample_rate_hz"])
    )
    with replay.ProcessPoolExecutor(
        max_workers=1, mp_context=replay.mp.get_context("spawn")
    ) as pool:
        gps, image = pool.submit(
            _worker_preprocess,
            values,
            start,
            1 / rep["sample_rate_hz"],
            "L1",
            start + rep["whitening_pad_s"],
            end - rep["whitening_pad_s"],
            True,
        ).result()
    assert gps == int(start + rep["whitening_pad_s"])
    assert np.array_equal(
        image, replay.independent_image(values, ("L1", start, end), "L1", rep)
    )


@pytest.fixture
def binding_case(tmp_path, monkeypatch):
    from src.core import patch_producer, preprocessor, utils, data_loader

    c = SimpleNamespace(root=tmp_path / "checkout")
    c.root.mkdir()
    qualified, extra = {}, {}
    for module, role in (
        (patch_producer, "patch_producer"),
        (preprocessor, "preprocessor"),
        (utils, None),
        (data_loader, None),
    ):
        relative = "src/core/" + module.__name__.split(".")[-1] + ".py"
        path = c.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic frozen source")
        monkeypatch.setattr(module, "__file__", str(path))
        if role:
            qualified[role] = {"path": relative, "current_sha256": replay._hash(path)}
        else:
            extra[relative] = replay._hash(path)
    config = {"preprocessing": {"synthetic": "bound"}}
    config_path = c.root / "config.yaml"
    config_path.write_text("preprocessing:\n  synthetic: bound\n")
    monkeypatch.setattr(preprocessor, "_CFG", config)
    qualified["runtime_config"] = {
        "path": "config.yaml",
        "current_sha256": replay._hash(config_path),
    }
    native_binding = sealed({"synthetic": "native"})
    c.method = sealed(
        dict(
            qualified_sources=qualified, native_binding_digest=native_binding["digest"]
        )
    )
    method_path = tmp_path / "method.json"
    write_json(method_path, c.method)
    method_contract_path = c.root / "method-contract.json"
    (c.root / "native-contract.json").write_text("{}")
    write_json(
        method_contract_path,
        dict(
            native_replay=dict(
                contract_path="native-contract.json",
                contract_sha256="synthetic",
                source_freeze="f" * 40,
            )
        ),
    )
    c.contract = dict(
        schema_version=1,
        status="FULL_EXPANDED_CALIBRATION_PREPROCESSING_REPLAY_V1",
        source_paths=list(replay.SOURCES),
        boundary=replay.BOUNDARY,
        measurement_rule=replay.MEASUREMENT,
        population_rule=replay.POPULATION,
        image_storage_rule=replay.STORAGE,
        automatic_resume=False,
        additional_runtime_source_pins=extra,
        method_contract=dict(
            path="method-contract.json",
            sha256=replay._hash(method_contract_path),
            source_freeze="f" * 40,
            evidence_sha256=replay._hash(method_path),
        ),
    )
    contract_path = c.root / "contract.json"
    write_json(contract_path, c.contract)
    monkeypatch.setattr(replay, "source_audit", lambda *a: {"test": "pinned"})
    monkeypatch.setattr(replay, "preflight", lambda **kw: c.method)
    monkeypatch.setattr(
        replay,
        "native_bind",
        lambda **kw: (SimpleNamespace(allowed={"synthetic"}), native_binding),
    )
    c.args = dict(
        root=c.root,
        contract_path=contract_path,
        contract_sha=replay._hash(contract_path),
        source_freeze="f" * 40,
        recovery_dir=tmp_path / "recovery",
        native_dir=tmp_path / "native",
        binding_path=tmp_path / "binding",
        binding_sha="synthetic",
        method_path=method_path,
    )
    return c


def test_full_method_binding_import_and_runtime_guard(binding_case):
    provider, binding = replay.bind(**binding_case.args)
    assert provider.allowed == {"synthetic"}
    assert binding["method"] == binding_case.method
    assert binding["boundary"] == replay.BOUNDARY
    assert "gwpy" in binding["runtime"]["packages"]


@pytest.mark.parametrize(
    "fault",
    [
        "version",
        "boundary",
        "rule",
        "resume",
        "extra_sources",
        "method",
        "config",
        "module",
    ],
)
def test_full_method_binding_fails_closed(binding_case, monkeypatch, fault):
    c = binding_case
    c.contract = deepcopy(c.contract)
    if fault in ("version", "boundary", "rule", "resume", "extra_sources"):
        if fault == "version":
            c.contract["schema_version"] = True
        elif fault == "boundary":
            c.contract["boundary"]["score_values_read"] = True
        elif fault == "rule":
            c.contract["population_rule"] = "drop invalid contexts"
        elif fault == "resume":
            c.contract["automatic_resume"] = True
        else:
            c.contract["additional_runtime_source_pins"].pop("src/core/utils.py")
        write_json(c.args["contract_path"], c.contract)
        c.args["contract_sha"] = replay._hash(c.args["contract_path"])
    elif fault == "method":
        monkeypatch.setattr(replay, "preflight", lambda **kw: sealed({"changed": True}))
    elif fault == "config":
        from src.core import preprocessor

        monkeypatch.setattr(preprocessor, "_CFG", {"changed": True})
    else:
        from src.core import patch_producer

        foreign = c.root / "foreign.py"
        foreign.write_text("foreign")
        monkeypatch.setattr(patch_producer, "__file__", str(foreign))
    with pytest.raises(InputCoverageError):
        replay.bind(**c.args)
