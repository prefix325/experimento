META_SOURCE_COLUMNS = ["faultNumber", "simulationRun", "sample"]
X_COLUMNS = [f"xmeas_{i}" for i in range(1, 42)] + [f"xmv_{i}" for i in range(1, 12)]
BLIND_COLUMNS = ["blind_run_id", "sample", *X_COLUMNS]
GROUND_TRUTH_COLUMNS = ["blind_run_id", "simulationRun", "sample", "y"]

PROHIBITED_KEYS = {
    "y",
    "is_anomaly",
    "faultnumber",
    "fault_number",
    "fault",
    "fault_name",
    "ground_truth",
    "dpca",
    "t2",
    "hotelling_t2",
    "spe",
    "q_statistic",
}

PROHIBITED_TEXT_PATTERNS = [
    r"\bidv\b",
    r"idv\s*\(?\s*13\s*\)?",
    r"\btep\b",
    r"tennessee\s+eastman",
    r"fault\s*number",
    r"ground\s*truth",
    r"is_anomaly",
    r"hotelling",
    r"\bdpca\b",
    r"\bspe\s*/?\s*q\b",
]

DECISIONS = {"NORMAL", "EVIDENCE_INSUFFICIENT", "ANOMALY"}
EVIDENCE_CLAIMS = {"HIGH", "LOW", "INCREASE", "REDUCTION", "VARIABILITY"}
LLM_FORBIDDEN_TEMPORAL_KEYS = {"window_id", "sample_start", "sample_end"}
LLM_FORBIDDEN_IDENTIFIER_KEYS = {"blind_run_id", "simulationrun"}
