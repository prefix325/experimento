from __future__ import annotations

import json
import os
import math
from datetime import datetime, timezone
from pathlib import Path

from .checkpoint import CheckpointStore
from .config import config_sha256, validate_development_config
from .constants import X_COLUMNS
from .dataset import load_blind_dataset
from .dpca import DPCAModel
from .frozen_dpca import load_frozen_dpca
from .hashing import sha256_file, sha256_text
from .leakage import validate_llm_payload
from .llm_runtime import LlamaServer
from .normalization import Standardizer
from .offline import verify_mount_permissions, verify_network_none
from .prompting import build_payload, render_prompt
from .records import append_jsonl, build_internal_llm_record
from .selection import apply_blind_mapping_all, apply_run_selection, load_run_selection, parse_run_block
from .windowing import iter_causal_windows
from .detection import FullWindowRefreshTracker
from .governance import inspect_static_gates, require_real_start


def _run_legacy_detectors(config: dict, results_dir: str | Path, normal_dir: str | Path, test_dir: str | Path, model_dir: str | Path, prompt_path: str | Path, schema_path: str | Path) -> dict:
    validate_development_config(config)
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    experiment_id = os.environ.get("EXPERIMENT_ID", f"{config['experiment_id_prefix']}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")

    verify_network_none(results_dir / "logs" / "network_check.json")
    permissions = verify_mount_permissions([normal_dir, test_dir, model_dir], results_dir)
    (results_dir / "logs" / "mount_permissions.json").write_text(json.dumps(permissions, indent=2) + "\n", encoding="utf-8")

    normal = load_blind_dataset(normal_dir, config.get("normal_run_limit"))
    test = load_blind_dataset(test_dir, config.get("test_run_limit"))
    standardizer = Standardizer.fit(normal)
    normal_z = standardizer.transform_frame(normal)
    test_z = standardizer.transform_frame(test)

    dpca_config = config["dpca"]
    model = DPCAModel.fit(
        normal_z,
        lags=int(dpca_config["lags"]),
        n_components=dpca_config.get("n_components"),
        variance_target=float(dpca_config["variance_target"]),
        threshold_quantile=float(dpca_config["threshold_quantile"]),
        persistence=int(dpca_config["alarm_persistence"]),
    )
    dpca_scores = model.score(test_z)
    dpca_path = results_dir / "raw_dpca" / "metrics.jsonl"
    for record in dpca_scores.to_dict(orient="records"):
        for key in ("t2", "spe"):
            if isinstance(record[key], float) and math.isnan(record[key]):
                record[key] = None
        record.update({"experiment_id": experiment_id, "t2_limit": model.t2_limit, "spe_limit": model.spe_limit})
        append_jsonl(dpca_path, record)

    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    llm_config = config["llm"]
    model_path = Path(model_dir) / llm_config["model_file"]
    decisions_path = results_dir / "raw_llm" / "decisions.jsonl"
    with LlamaServer(model_path, llm_config, results_dir / "logs") as runtime:
        for window in iter_causal_windows(
            test_z,
            int(config["window_samples"]),
            int(config["stride_samples"]),
            config.get("max_windows_per_run"),
        ):
            payload = build_payload(window, config["representation"], int(config["sample_interval_minutes"]))
            validate_llm_payload(payload)
            prompt = render_prompt(payload, prompt_path)
            started_at = datetime.now(timezone.utc)
            output, usage, latency_ms = runtime.infer(prompt, schema)
            ended_at = datetime.now(timezone.utc)
            record = build_internal_llm_record(
                experiment_id=experiment_id,
                window=window,
                payload=payload,
                prompt_hash=sha256_text(prompt),
                model_hash=os.environ.get("MODEL_SHA256"),
                usage=usage,
                inference_start=started_at.isoformat(),
                inference_end=ended_at.isoformat(),
                latency_ms=latency_ms,
                output=output,
                sample_interval_minutes=int(config["sample_interval_minutes"]),
            )
            append_jsonl(decisions_path, record)

    completion = {
        "status": config["status"],
        "experiment_id": experiment_id,
        "normal_rows": len(normal),
        "test_rows": len(test),
        "x_columns": len(X_COLUMNS),
        "llm_records": sum(1 for _ in decisions_path.open(encoding="utf-8")),
        "dpca_records": len(dpca_scores),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    (results_dir / "detectors_complete.json").write_text(json.dumps(completion, indent=2) + "\n", encoding="utf-8")
    return completion


def _verified_artifact(config_root: Path, artifacts: dict, name: str) -> tuple[Path, str]:
    specification = artifacts[name]
    path = config_root / specification["file"]
    observed = sha256_file(path)
    if observed != specification["sha256"]:
        raise RuntimeError(f"Frozen artifact hash mismatch: {name}")
    return path, observed


def _require_checkpointed_operational_gate(
    config: dict,
    operational_amendment: dict | None,
    governance_repo_root: str | Path | None,
    governance_workspace_root: str | Path | None,
):
    """Require the shared formal operational authority before dataset access."""
    if config.get("methodology_frozen") is not True:
        raise RuntimeError("Checkpointed formal execution requires a frozen methodology")
    if governance_repo_root is None or governance_workspace_root is None:
        raise RuntimeError("Checkpointed formal execution requires operational governance roots")
    report = inspect_static_gates(governance_repo_root, governance_workspace_root)
    require_real_start(report)
    if report.status != "REAL START READY":
        raise RuntimeError(f"Unexpected formal operational gate status: {report.status}")
    formal_path = Path(report.evidence["formal"])
    governed_config = json.loads(formal_path.read_text(encoding="utf-8-sig"))
    governed_sha256 = config_sha256(governed_config)
    if operational_amendment is None:
        if config_sha256(config) != governed_sha256:
            raise RuntimeError("Loaded formal configuration differs from operational gate authority")
    elif (
        governed_sha256 != operational_amendment["base_configuration_sha256"]
        or config_sha256(config)
        != operational_amendment["effective_configuration_sha256"]
    ):
        raise RuntimeError("Operational amendment configuration provenance mismatch")
    return report


def _run_checkpointed_detectors(
    config: dict,
    results_dir: str | Path,
    normal_dir: str | Path,
    test_dir: str | Path,
    model_dir: str | Path,
    prompt_path: str | Path,
    schema_path: str | Path,
    run_block: str | None,
    cohort: str,
    methodological_amendment: dict | None,
    operational_amendment: dict | None,
    detector: str,
    dpca_run_block: str | None,
    governance_repo_root: str | Path | None,
    governance_workspace_root: str | Path | None,
) -> dict:
    validate_development_config(config)
    _require_checkpointed_operational_gate(
        config,
        operational_amendment,
        governance_repo_root,
        governance_workspace_root,
    )

    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    verify_network_none(results_dir / "logs" / "network_check.json")
    permissions = verify_mount_permissions([normal_dir, test_dir, model_dir], results_dir)
    (results_dir / "logs" / "mount_permissions.json").write_text(
        json.dumps(permissions, indent=2) + "\n", encoding="utf-8"
    )

    config_root = Path(schema_path).parent
    artifacts = config["artifacts"]
    prompt_path = Path(prompt_path)
    schema_path = Path(schema_path)
    if sha256_file(prompt_path) != artifacts["prompt_template"]["sha256"]:
        raise RuntimeError("Frozen prompt hash mismatch")
    if sha256_file(schema_path) != artifacts["output_schema"]["sha256"]:
        raise RuntimeError("Frozen output-schema hash mismatch")
    representation_path, representation_hash = _verified_artifact(config_root, artifacts, "representation_contract")
    evaluation_path, evaluation_hash = _verified_artifact(config_root, artifacts, "evaluation_contract")
    if cohort not in {"target", "normal_holdout"}:
        raise ValueError("Formal cohort must be target or normal_holdout")
    if methodological_amendment is None:
        raise RuntimeError("Checkpointed formal execution requires the post-freeze methodological amendment")
    if detector not in {"llm", "dpca", "both"}:
        raise ValueError("detector must be llm, dpca or both")
    selection_artifact = (
        "formal_run_selection" if cohort == "target" else "formal_normal_holdout_selection"
    )
    selection_path, selection_hash = _verified_artifact(config_root, artifacts, selection_artifact)
    dpca_reference_path, dpca_reference_hash = _verified_artifact(config_root, artifacts, "dpca_reference")
    dpca_artifact_path, dpca_artifact_hash = _verified_artifact(config_root, artifacts, "dpca_artifact")
    _, h3_reference_hash = _verified_artifact(config_root, artifacts, "h3_evidence_reference")

    selection = load_run_selection(selection_path, selection_hash)
    test_all = load_blind_dataset(test_dir)
    dpca_test, ordered_dpca_ids = apply_blind_mapping_all(test_all, int(selection["seed"]))
    llm_test, ordered_llm_ids = apply_run_selection(test_all, selection)
    llm_limit_key = "llm_target_run_limit" if cohort == "target" else "llm_normal_holdout_run_limit"
    dpca_limit_key = "dpca_target_run_limit" if cohort == "target" else "dpca_normal_holdout_run_limit"
    if len(ordered_llm_ids) != int(config["formal_scope"][llm_limit_key]):
        raise RuntimeError(f"Formal selection count differs from {llm_limit_key}")
    if len(ordered_dpca_ids) != int(config["formal_scope"][dpca_limit_key]):
        raise RuntimeError(f"Formal DPCA universe differs from {dpca_limit_key}")
    block_ids = parse_run_block(run_block, ordered_llm_ids)
    dpca_block_ids = parse_run_block(dpca_run_block, ordered_dpca_ids)
    llm_test = llm_test[llm_test["blind_run_id"].isin(block_ids)].copy()

    dpca_config = config["dpca"]
    frozen = load_frozen_dpca(
        dpca_reference_path,
        dpca_artifact_path,
        dpca_reference_hash,
        dpca_artifact_hash,
        dpca_config,
    )
    dpca_test_z = frozen.standardizer.transform_frame(dpca_test)
    llm_test_z = frozen.standardizer.transform_frame(llm_test)

    model_path = Path(model_dir) / config["llm"]["model_file"]
    observed_model_hash = sha256_file(model_path)
    if observed_model_hash != config["llm"]["model_sha256"]:
        raise RuntimeError("Frozen model hash mismatch")
    image_digest = os.environ.get("DOCKER_IMAGE_DIGEST")
    if not image_digest:
        raise RuntimeError("DOCKER_IMAGE_DIGEST is required for formal checkpointing")
    checkpoint_configuration_sha256 = (
        operational_amendment["base_configuration_sha256"]
        if operational_amendment is not None
        else config_sha256(config)
    )
    frozen_hashes = {
        "configuration_sha256": checkpoint_configuration_sha256,
        "prompt_sha256": artifacts["prompt_template"]["sha256"],
        "model_sha256": observed_model_hash,
        "image_digest": image_digest,
        "output_schema_sha256": artifacts["output_schema"]["sha256"],
        "representation_contract_sha256": representation_hash,
        "evaluation_contract_sha256": evaluation_hash,
        "run_selection_sha256": selection_hash,
        "dpca_reference_sha256": dpca_reference_hash,
        "dpca_artifact_sha256": dpca_artifact_hash,
        "h3_reference_sha256": h3_reference_hash,
        "methodological_amendment_sha256": methodological_amendment["_sha256"],
    }
    operational_provenance = (
        {
            "amendment_id": operational_amendment["amendment_id"],
            "amendment_sha256": operational_amendment["_sha256"],
            "base_configuration_sha256": operational_amendment[
                "base_configuration_sha256"
            ],
            "effective_configuration_sha256": operational_amendment[
                "effective_configuration_sha256"
            ],
            "changed_parameter": operational_amendment["changed_parameter"],
            "from": int(operational_amendment["from"]),
            "to": int(operational_amendment["to"]),
        }
        if operational_amendment is not None
        else None
    )
    dpca_checkpoints = CheckpointStore(results_dir / "dpca", frozen_hashes)
    llm_checkpoints = CheckpointStore(
        results_dir / "llm",
        frozen_hashes,
        operational_provenance=operational_provenance,
    )
    pending_dpca = (
        [run_id for run_id in dpca_block_ids if dpca_checkpoints.inspect(run_id) != "COMPLETE"]
        if detector in {"dpca", "both"}
        else []
    )
    pending_llm = (
        [run_id for run_id in block_ids if llm_checkpoints.inspect(run_id) != "COMPLETE"]
        if detector in {"llm", "both"}
        else []
    )
    experiment_id = f"{config['experiment_id_prefix']}-{frozen_hashes['configuration_sha256'][:12]}"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    for blind_run_id in pending_dpca:
        attempt = dpca_checkpoints.begin_run(blind_run_id)
        try:
            run = dpca_test_z[dpca_test_z["blind_run_id"] == blind_run_id].copy()
            dpca_scores = frozen.model.score(run)
            dpca_path = attempt.artifact("dpca_metrics.jsonl")
            for record in dpca_scores.to_dict(orient="records"):
                for key in ("t2", "spe"):
                    if isinstance(record[key], float) and math.isnan(record[key]):
                        record[key] = None
                record.update({
                    "experiment_id": experiment_id,
                    "t2_limit": frozen.model.t2_limit,
                    "spe_limit": frozen.model.spe_limit,
                })
                append_jsonl(dpca_path, record)
            dpca_checkpoints.complete_run(
                attempt, ["dpca_metrics.jsonl"], {"dpca_records": len(dpca_scores)}
            )
        except BaseException as exc:
            dpca_checkpoints.mark_failed(attempt, f"{type(exc).__name__}: {exc}")
            raise

    if pending_llm:
        with LlamaServer(model_path, config["llm"], results_dir / "logs") as runtime:
            for blind_run_id in pending_llm:
                attempt = llm_checkpoints.begin_run(blind_run_id)
                try:
                    run = llm_test_z[llm_test_z["blind_run_id"] == blind_run_id].copy()
                    decisions_path = attempt.artifact("llm_decisions.jsonl")
                    detection_path = attempt.artifact("detection_summary.json")
                    llm_records = 0
                    tracker = FullWindowRefreshTracker(
                        int(config["window_samples"]),
                        int(config["stride_samples"]),
                        target=cohort == "target",
                    )
                    for window in iter_causal_windows(
                        run,
                        int(config["window_samples"]),
                        int(config["stride_samples"]),
                        config.get("max_windows_per_run"),
                    ):
                        payload = build_payload(
                            window, config["representation"], int(config["sample_interval_minutes"])
                        )
                        validate_llm_payload(payload)
                        prompt = render_prompt(payload, prompt_path)
                        started_at = datetime.now(timezone.utc)
                        output, usage, latency_ms = runtime.infer(prompt, schema)
                        ended_at = datetime.now(timezone.utc)
                        detection = tracker.observe(
                            window.window_id,
                            output["decision"],
                            eligible=(
                                cohort != "target"
                                or window.sample_end
                                >= int(config["fault_onset_sample"])
                            ),
                        )
                        record = build_internal_llm_record(
                            experiment_id=experiment_id,
                            window=window,
                            payload=payload,
                            prompt_hash=sha256_text(prompt),
                            model_hash=observed_model_hash,
                            usage=usage,
                            inference_start=started_at.isoformat(),
                            inference_end=ended_at.isoformat(),
                            latency_ms=latency_ms,
                            output=output,
                            sample_interval_minutes=int(config["sample_interval_minutes"]),
                        )
                        record["detection"] = detection.to_dict()
                        append_jsonl(decisions_path, record)
                        llm_records += 1
                        if detection.should_stop:
                            break
                    final_detection = tracker.finalize()
                    detection_path.write_text(
                        json.dumps(final_detection.to_dict(), indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )
                    llm_checkpoints.complete_run(
                        attempt,
                        ["llm_decisions.jsonl", "detection_summary.json"],
                        {
                            "llm_records": llm_records,
                            "early_stop": int(final_detection.should_stop),
                        },
                    )
                except BaseException as exc:
                    llm_checkpoints.mark_failed(attempt, f"{type(exc).__name__}: {exc}")
                    raise

    completed_dpca = dpca_checkpoints.completed_runs()
    completed_llm = llm_checkpoints.completed_runs()
    dpca_complete = set(completed_dpca) == set(ordered_dpca_ids)
    llm_complete = set(completed_llm) == set(ordered_llm_ids)
    lot_status = (
        "COMPLETE" if dpca_complete and llm_complete else "PARTIAL"
    )
    summary = {
        "status": lot_status,
        "lot_status": lot_status,
        "cohort": cohort,
        "detector_request": detector,
        "experiment_id": experiment_id,
        "dpca": {
            "status": "COMPLETE" if dpca_complete else "PARTIAL",
            "formal_runs": len(ordered_dpca_ids),
            "manual_block_runs": len(dpca_block_ids),
            "completed_runs": len(completed_dpca),
            "remaining_runs": len(set(ordered_dpca_ids) - set(completed_dpca)),
        },
        "llm": {
            "status": "COMPLETE" if llm_complete else "PARTIAL",
            "formal_selected_runs": len(ordered_llm_ids),
            "manual_block_runs": len(block_ids),
            "completed_runs": len(completed_llm),
            "remaining_runs": len(set(ordered_llm_ids) - set(completed_llm)),
        },
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    (results_dir / "checkpoint_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if summary["status"] == "COMPLETE":
        (results_dir / "detectors_complete.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return summary


def run_detectors(
    config: dict,
    results_dir: str | Path,
    normal_dir: str | Path,
    test_dir: str | Path,
    model_dir: str | Path,
    prompt_path: str | Path,
    schema_path: str | Path,
    run_block: str | None = None,
    cohort: str | None = None,
    methodological_amendment: dict | None = None,
    operational_amendment: dict | None = None,
    detector: str = "both",
    dpca_run_block: str | None = None,
    governance_repo_root: str | Path | None = None,
    governance_workspace_root: str | Path | None = None,
) -> dict:
    if config.get("checkpoint_resume", {}).get("enabled") is True:
        if cohort is None:
            raise ValueError("--cohort is required for checkpointed formal execution")
        return _run_checkpointed_detectors(
            config,
            results_dir,
            normal_dir,
            test_dir,
            model_dir,
            prompt_path,
            schema_path,
            run_block,
            cohort,
            methodological_amendment,
            operational_amendment,
            detector,
            dpca_run_block,
            governance_repo_root,
            governance_workspace_root,
        )
    if run_block is not None or cohort is not None or detector != "both" or dpca_run_block is not None:
        raise ValueError("--run-block/--cohort require checkpoint_resume.enabled=true")
    return _run_legacy_detectors(config, results_dir, normal_dir, test_dir, model_dir, prompt_path, schema_path)
