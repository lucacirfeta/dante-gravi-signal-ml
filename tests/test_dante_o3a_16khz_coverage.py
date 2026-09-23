"""Coverage-audit checks independent of the live GWOSC service."""

from scripts.audit_dante_o3a_16khz_coverage import frame_interval, uncovered_segments
import pytest


def test_frame_interval_distinguishes_duration_from_sample_rate():
    assert frame_interval(
        "https://gwosc.org/archive/data/O3a_16KHZ_R1/1237319680/"
        "H-H1_GWOSC_O3a_16KHZ_R1-1238163456-4096.hdf5?format=json",
        "H1",
        16,
    ) == (1238163456, 1238167552)


def test_frame_interval_rejects_wrong_rate_or_host():
    url = (
        "https://gwosc.org/archive/data/O3a_4KHZ_R1/1237319680/"
        "H-H1_GWOSC_O3a_4KHZ_R1-1238163456-4096.hdf5"
    )
    with pytest.raises(ValueError):
        frame_interval(url, "H1", 16)
    with pytest.raises(ValueError):
        frame_interval(url.replace("gwosc.org", "example.org"), "H1", 4)


def test_uncovered_segments_detects_internal_and_boundary_gaps():
    assert uncovered_segments([[0, 10], [20, 30]], [(2, 5), (5, 8), (20, 25)]) == [
        (0, 2),
        (8, 10),
        (25, 30),
    ]
    assert uncovered_segments([[0, 10], [20, 30]], [(0, 10), (15, 35)]) == []
