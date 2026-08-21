from pathlib import Path


REPO = Path(__file__).resolve().parents[3]


def test_official_manifest_only_branch_precedes_unsafe_online_preparation():
    script = (REPO / "scripts" / "prepare_online.ps1").read_text(encoding="utf-8")
    branch = script.index("if ($ManifestOnlyRefreeze)")
    first_online_action = script.index("$repo = Get-RepoRoot")

    assert branch < first_online_action
    assert "regenerate_refreeze_preparation_manifest.ps1" in script[branch:first_online_action]


def test_refreeze_generator_is_manifest_only_and_fail_closed():
    script = (
        REPO / "scripts" / "regenerate_refreeze_preparation_manifest.ps1"
    ).read_text(encoding="utf-8")
    lowered = script.lower()

    assert "docker run" not in lowered
    assert "run-detectors" not in lowered
    assert "prepare-data" not in lowered
    assert "technical-acceptance" not in lowered
    assert "get-sha256" in lowered
    assert "binary_sha256_only" in lowered
    assert "old_preparation_sha256" in lowered
    assert "stale_preparation_manifest" in lowered


def test_construct_only_reports_refreeze_preparation_continuity():
    common = (REPO / "scripts" / "common.ps1").read_text(encoding="utf-8")
    construct = (
        REPO / "scripts" / "run_formal_batch_offline.ps1"
    ).read_text(encoding="utf-8")

    assert "Assert-RefreezePreparationManifest" in common
    for field in (
        "preparation_manifest_current",
        "formal_hash_match",
        "method_freeze_match",
        "technical_acceptance_match",
    ):
        assert field in construct
    assert "docker_executed = $false" in construct
    assert "formal_run_started = $false" in construct
    assert "llm_inference_count = 0" in construct
    assert "-AllowBlocked:$ConstructOnly" in construct
    assert "post_freeze_operational_amendment_001.json" in construct
