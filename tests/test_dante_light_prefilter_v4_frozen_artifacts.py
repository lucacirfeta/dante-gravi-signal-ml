from scripts.verify_dante_light_prefilter_v4_freeze import verify


def test_committed_v4_freeze_is_outcome_blind_and_unopened():
    result = verify()
    assert result == {
        "status": "PASS_IDENTITY_ONLY_NOT_OPENED",
        "rows": 2030,
        "trials": 375,
        "access_log_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }
