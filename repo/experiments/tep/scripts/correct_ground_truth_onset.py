from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


EXPECTED_COLUMNS = ["blind_run_id", "simulationRun", "sample", "y"]
EXPECTED_RUNS = 500
EXPECTED_SAMPLES = 960
FAULT_ONSET_SAMPLE = 161


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rewrite_file(source: Path, destination: Path) -> tuple[int, set[int]]:
    rows = 0
    run_ids: set[int] = set()
    with gzip.open(source, "rt", encoding="utf-8", newline="") as input_handle:
        reader = csv.DictReader(input_handle)
        if reader.fieldnames != EXPECTED_COLUMNS:
            raise ValueError(f"Unexpected ground-truth schema in {source}")
        with destination.open("wb") as raw_output:
            with gzip.GzipFile(fileobj=raw_output, mode="wb", filename="", mtime=0) as compressed:
                with __import__("io").TextIOWrapper(compressed, encoding="utf-8", newline="") as output_handle:
                    writer = csv.DictWriter(output_handle, fieldnames=EXPECTED_COLUMNS, lineterminator="\n")
                    writer.writeheader()
                    for row in reader:
                        sample = int(row["sample"])
                        run_id = int(row["simulationRun"])
                        if not 1 <= sample <= EXPECTED_SAMPLES:
                            raise ValueError(f"Out-of-range sample {sample} in {source}")
                        row["y"] = "1" if sample >= FAULT_ONSET_SAMPLE else "0"
                        writer.writerow(row)
                        run_ids.add(run_id)
                        rows += 1
    return rows, run_ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ground_truth_dir", type=Path)
    parser.add_argument("preparation_manifest", type=Path)
    parser.add_argument("correction_manifest", type=Path)
    args = parser.parse_args()

    ground_truth_dir = args.ground_truth_dir.resolve()
    files = sorted(ground_truth_dir.glob("*.csv.gz"))
    if len(files) != 10:
        raise ValueError(f"Expected 10 ground-truth parts, found {len(files)}")

    backup_dir = ground_truth_dir.parent / "ground_truth_pre_onset_161"
    backup_dir.mkdir(parents=False, exist_ok=True)
    records = []
    all_runs: set[int] = set()
    total_rows = 0

    for source in files:
        backup = backup_dir / source.name
        if not backup.exists():
            shutil.copy2(source, backup)
        before_hash = sha256_file(backup)
        temporary = source.with_suffix(source.suffix + ".tmp")
        rows, run_ids = rewrite_file(backup, temporary)
        temporary.replace(source)
        after_hash = sha256_file(source)
        records.append({
            "file": source.name,
            "before_sha256": before_hash,
            "after_sha256": after_hash,
            "rows": rows,
        })
        all_runs.update(run_ids)
        total_rows += rows

    if all_runs != set(range(1, EXPECTED_RUNS + 1)):
        raise ValueError("Ground truth does not contain simulationRun 1..500 exactly")
    if total_rows != EXPECTED_RUNS * EXPECTED_SAMPLES:
        raise ValueError("Ground truth does not contain 500 x 960 rows")

    correction = {
        "status": "METHODOLOGICAL_OFF_BY_ONE_CORRECTION_APPLIED",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "previous_rule": "y = 1 when sample >= 160",
        "corrected_rule": "y = 1 when sample >= 161",
        "normal_samples": "1..160",
        "post_fault_samples": "161..960",
        "fault_onset_sample": FAULT_ONSET_SAMPLE,
        "x_values_read_or_modified": False,
        "backup_directory": str(backup_dir),
        "simulation_runs": len(all_runs),
        "samples_per_run": EXPECTED_SAMPLES,
        "total_rows": total_rows,
        "files": records,
    }
    args.correction_manifest.write_text(
        json.dumps(correction, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    if args.preparation_manifest.exists():
        manifest = json.loads(args.preparation_manifest.read_text(encoding="utf-8-sig"))
        hashes = {record["file"]: record["after_sha256"] for record in records}
        for item in manifest.get("dataset_files", []):
            if item.get("role") == "ground_truth":
                name = Path(item["relative_path"]).name
                item["sha256"] = hashes[name]
        manifest["temporal_label_correction"] = {
            "status": correction["status"],
            "previous_rule": correction["previous_rule"],
            "corrected_rule": correction["corrected_rule"],
            "fault_onset_sample": FAULT_ONSET_SAMPLE,
            "correction_manifest": str(args.correction_manifest),
        }
        args.preparation_manifest.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
