"""Metadata bookkeeping tests; not scientific qualification."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "metadata_proposal", ROOT / "scripts/snapshot_dante_o4b_metadata_proposal.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.mark.parametrize(
    "first,second,expected",
    [
        ([[0, 5], [8, 12]], [[3, 10]], [[3, 5], [8, 10]]),
        ([[0, 5]], [[5, 8]], []),
        ([], [[0, 5]], []),
        ([[0, 5]], [], []),
        ([[0, 5]], [[0, 5]], [[0, 5]]),
    ],
)
def test_intersection(first, second, expected):
    assert module.intersect(first, second) == expected


@pytest.mark.parametrize(
    "first,second,expected",
    [
        ([[0, 10]], [[2, 4], [6, 8]], [[0, 2], [4, 6], [8, 10]]),
        ([[0, 5], [8, 12]], [[3, 10]], [[0, 3], [10, 12]]),
        ([[0, 5]], [[0, 5]], []),
        ([[0, 5]], [], [[0, 5]]),
        ([[0, 5]], [[5, 7]], [[0, 5]]),
    ],
)
def test_subtraction(first, second, expected):
    assert module.subtract(first, second) == expected


@pytest.mark.parametrize(
    "segments",
    [
        [[0, 0]],
        [[-1, 3]],
        [[0, 11]],
        [[0, 5], [4, 8]],
        [[5, 8], [0, 3]],
        [[True, 3]],
        [[0.0, 3]],
        [[0, 3, 3]],
    ],
)
def test_bad_segments(segments):
    payload = dict(dataset="O4b", id="H1_DATA", start=0, end=10, segments=segments)
    with pytest.raises(ValueError):
        module.parse_segments(payload, "O4b", "H1_DATA", 0, 10)


@pytest.mark.parametrize(
    "key,value",
    [
        ("dataset", "O4a"),
        ("id", "L1_DATA"),
        ("start", 1),
        ("end", 11),
    ],
)
def test_query_identity(key, value):
    payload = dict(dataset="O4b", id="H1_DATA", start=0, end=10, segments=[])
    payload[key] = value
    with pytest.raises(ValueError):
        module.parse_segments(payload, "O4b", "H1_DATA", 0, 10)


@pytest.mark.parametrize(
    "url",
    [
        "http://gwosc.org/timeline/segments/json/O4b/",
        "https://example.com/timeline/segments/json/",
        "https://gwosc.org/archive/links/O4b/H1/",
        "https://gwosc.org/file.hdf5",
    ],
)
def test_no_strain_or_external_urls(url):
    with pytest.raises(ValueError):
        module.check_url(url)


def test_request_does_not_admit_science():
    request = json.loads(
        (ROOT / "config/dante_o4b_metadata_proposal_v1.json").read_text()
    )
    module.validate_request(request)
    request["scientific_execution_ready"] = True
    with pytest.raises(ValueError):
        module.validate_request(request)


def test_no_overwrite(tmp_path):
    path = tmp_path / "receipt.json"
    module.save_json(path, {"retained": True})
    with pytest.raises(FileExistsError):
        module.save_json(path, {"retained": False})
    assert json.loads(path.read_text()) == {"retained": True}


def test_interval_accounting_exhaustive_small_grid():
    available = [[0, 12]]
    for left in range(12):
        for right in range(left + 1, 13):
            good = module.intersect(available, [[left, right]])
            rest = module.subtract(available, good)
            assert module.seconds(good) + module.seconds(rest) == 12
            assert module.intersect(good, rest) == []


def test_fixture_snapshot_and_existing_destination(tmp_path, monkeypatch):
    request = json.loads(
        (ROOT / "config/dante_o4b_metadata_proposal_v1.json").read_text()
    )
    request.update(gps_start=0, gps_end=10)
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request))
    metadata = {
        "shortName": request["dataset"],
        "npoints": request["sample_rate_hz"] * 4096,
        "duration": 4096,
        "bits": [
            {"shortName": flag, "mask": mask}
            for mask, key in ((0, "dq_flags"), (1, "no_hw_inj_flags"))
            for flag in request[key]
        ],
    }

    def fake_fetch(url, transport):
        if url == request["dataset_metadata_url"]:
            return json.dumps(metadata).encode()
        flag_id = url.split("/")[-4]
        spans = [[0, 10]]
        if flag_id.endswith("NO_CBC_HW_INJ"):
            spans = [[0, 4], [6, 10]]
        if flag_id.endswith("BURST_CAT2"):
            spans = [[1, 2]]
        return json.dumps(
            dict(dataset="O4b", id=flag_id, start=0, end=10, segments=spans)
        ).encode()

    monkeypatch.setattr(module, "fetch", fake_fetch)
    output = tmp_path / "snapshot"
    result = module.snapshot(request_path, output)
    assert len(result["timelines"]) == 42
    for detector in request["detectors"]:
        row = result["detectors"][detector]
        assert row["background_candidate_seconds"] == 8
        assert row["not_passing_no_hw_inj_seconds"] == 2
        assert row["dq_annotations"]["BURST_CAT2"] == {
            "data_passing_seconds": 1,
            "used_as_veto": False,
        }
    assert result["population_allocation"] is None
    assert result["context_coverage_verified"] is False
    original = (output / "proposal.json").read_bytes()
    monkeypatch.setattr(
        "sys.argv",
        ["snapshot", "--request", str(request_path), "--output", str(output)],
    )
    with pytest.raises(FileExistsError):
        module.main()
    assert (output / "proposal.json").read_bytes() == original
    assert not (output / "failure.json").exists()
