from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .config import load_config
from .dataset import prepare_blind_datasets
from .evaluation import evaluate_results
from .manifest import create_run_manifest, llama_cpp_version
from .pipeline import run_detectors
from .technical_acceptance import run_technical_acceptance
from .amendments import load_methodological_amendment, load_operational_amendment


DEFAULT_CONFIG_ROOT = Path("/opt/tep/config")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Local TEP LLM + DPCA experiment tools")
    commands = root.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare-data")
    prepare.add_argument("--source", required=True)
    prepare.add_argument("--normal-out", required=True)
    prepare.add_argument("--test-out", required=True)
    prepare.add_argument("--ground-truth-out", required=True)
    prepare.add_argument("--manifest-out", required=True)

    run = commands.add_parser("run-detectors")
    run.add_argument("--config", required=True)
    run.add_argument("--results", default="/results")
    run.add_argument("--normal", default="/data/normal")
    run.add_argument("--test", default="/data/test")
    run.add_argument("--models", default="/models")
    run.add_argument("--prompt", default=str(DEFAULT_CONFIG_ROOT / "prompt_template.txt"))
    run.add_argument("--schema", default=str(DEFAULT_CONFIG_ROOT / "output_schema.json"))
    run.add_argument(
        "--run-block",
        help="Optional 1-based ordinals/ranges within the immutable formal selection, for example 1-10,21",
    )
    run.add_argument("--cohort", choices=["target", "normal_holdout"])
    run.add_argument("--methodological-amendment")
    run.add_argument("--operational-amendment")
    run.add_argument("--detector", choices=["llm", "dpca", "both"], default="both")
    run.add_argument(
        "--dpca-run-block",
        help="Optional 1-based ordinals/ranges within the complete DPCA cohort run order",
    )
    run.add_argument("--governance-repo-root")
    run.add_argument("--governance-workspace-root")

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--config", required=True)
    evaluate.add_argument("--results", default="/results")
    evaluate.add_argument("--ground-truth", default="/ground_truth")
    evaluate.add_argument("--prompt", default=str(DEFAULT_CONFIG_ROOT / "prompt_template.txt"))
    evaluate.add_argument("--selection", default=str(DEFAULT_CONFIG_ROOT / "formal_run_selection.json"))
    evaluate.add_argument(
        "--normal-selection",
        default=str(DEFAULT_CONFIG_ROOT / "formal_normal_holdout_selection.json"),
    )
    evaluate.add_argument("--h3-reference", default=str(DEFAULT_CONFIG_ROOT / "h3_evidence_reference.json"))
    evaluate.add_argument("--normal-results")
    evaluate.add_argument("--methodological-amendment", required=True)

    commands.add_parser("runtime-version")

    acceptance = commands.add_parser("technical-acceptance")
    acceptance.add_argument("--config", required=True)
    acceptance.add_argument("--results", required=True)
    acceptance.add_argument("--models", default="/models")
    acceptance.add_argument("--prompt", default=str(DEFAULT_CONFIG_ROOT / "prompt_template.txt"))
    acceptance.add_argument("--schema", default=str(DEFAULT_CONFIG_ROOT / "output_schema.json"))
    acceptance.add_argument("--operational-amendment", required=True)
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "prepare-data":
        result = prepare_blind_datasets(args.source, args.normal_out, args.test_out, args.ground_truth_out, args.manifest_out)
    elif args.command == "run-detectors":
        base_config = load_config(args.config)
        amendment = (
            load_methodological_amendment(
                args.methodological_amendment, args.config, base_config
            )
            if args.methodological_amendment
            else None
        )
        config, operational_amendment = (
            load_operational_amendment(
                args.operational_amendment, args.config, base_config
            )
            if args.operational_amendment
            else (base_config, None)
        )
        result = run_detectors(
            config, args.results, args.normal, args.test, args.models, args.prompt, args.schema,
            args.run_block, args.cohort, amendment, operational_amendment,
            args.detector, args.dpca_run_block,
            args.governance_repo_root, args.governance_workspace_root,
        )
    elif args.command == "evaluate":
        config = load_config(args.config)
        amendment = load_methodological_amendment(
            args.methodological_amendment, args.config, config
        )
        result = evaluate_results(
            args.results,
            args.ground_truth,
            config,
            args.selection,
            args.normal_selection,
            args.h3_reference,
            args.normal_results,
            amendment,
        )
        create_run_manifest(args.results, config, args.prompt)
    elif args.command == "runtime-version":
        result = {"llama_cpp_version": llama_cpp_version(os.environ.get("LLAMA_SERVER_BIN", "/app/llama-server"))}
    elif args.command == "technical-acceptance":
        base_config = load_config(args.config, require_frozen=True)
        config, operational_amendment = load_operational_amendment(
            args.operational_amendment, args.config, base_config
        )
        result = run_technical_acceptance(
            config,
            args.results,
            args.models,
            args.prompt,
            args.schema,
            operational_amendment,
        )
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
