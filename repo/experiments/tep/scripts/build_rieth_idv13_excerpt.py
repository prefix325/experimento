import argparse
from pathlib import Path
import pandas as pd
import pyreadr

META = ["faultNumber", "simulationRun", "sample"]
X = [f"xmeas_{i}" for i in range(1, 42)] + [f"xmv_{i}" for i in range(1, 12)]
EXPECTED = META + X


def load_rdata(path, key):
    obj = pyreadr.read_r(str(path))
    if key not in obj:
        raise ValueError(f"Missing R object: {key}")
    df = obj[key].copy()
    if list(df.columns) != EXPECTED:
        raise ValueError("Unexpected Rieth schema: expected metadata + all 52 TEP variables")
    return df


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fault-free-training", required=True)
    p.add_argument("--fault-free-testing", required=True)
    p.add_argument("--faulty-testing", required=True)
    p.add_argument("--runs", type=int, default=10)
    p.add_argument("--out", default="experiments/tep/derived/rieth_idv13_pilot")
    a = p.parse_args()

    ff_train = load_rdata(a.fault_free_training, "fault_free_training")
    ff_test = load_rdata(a.fault_free_testing, "fault_free_testing")
    faulty = load_rdata(a.faulty_testing, "faulty_testing")
    faulty = faulty[faulty["faultNumber"].astype(int) == 13].copy()

    run_ids = list(range(1, a.runs + 1))
    parts = []
    for cohort, df in [("normal_reference", ff_train), ("normal_holdout", ff_test), ("idv13_test", faulty)]:
        z = df[df["simulationRun"].astype(int).isin(run_ids)].copy()
        z.insert(0, "cohort", cohort)
        if cohort == "idv13_test":
            # Approved 1-based convention: samples 1..160 are normal and the
            # first post-fault sample is 161. The former >= 160 rule was an
            # off-by-one methodological error.
            z["is_anomaly"] = (z["sample"].astype(int) >= 161).astype(int)
        else:
            z["is_anomaly"] = 0
        parts.append(z)

    data = pd.concat(parts, ignore_index=True)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    data[X].to_csv(out / "X.csv.gz", index=False, compression="gzip")
    data[["is_anomaly"]].to_csv(out / "y.csv.gz", index=False, compression="gzip")
    data[["cohort"] + META].to_csv(out / "metadata.csv.gz", index=False, compression="gzip")
    data[["cohort"] + META + ["is_anomaly"] + X].to_csv(out / "rieth_idv13_excerpt.csv.gz", index=False, compression="gzip")

    assert len(X) == 52
    assert len(data[X]) == len(data[["is_anomaly"]])
    print(f"rows={len(data)} x_columns={len(X)} y_columns=1 runs={a.runs}")


if __name__ == "__main__":
    main()
