from scripts.verify_dante_light_prefilter_v4_development import main


def test_frozen_v4_development_artifacts_recompute(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "verify_dante_light_prefilter_v4_development.py",
            "--artifact-dir",
            "artifacts/dante_light/prefilter_l4_v4_development",
        ],
    )
    assert main() == 0
