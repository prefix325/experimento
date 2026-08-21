"""Independent implementation of the frozen H3 evidence-scoring contract.

Only the structured evidence fields ``variable`` and ``claim`` select a
numeric rule.  ``observation`` is copied to the audit trail for provenance but
is never parsed, compared, or otherwise used in scoring.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import random
import statistics
from typing import Any, Iterable, Mapping, Sequence


CLAIMS = frozenset({"HIGH", "LOW", "INCREASE", "REDUCTION", "VARIABILITY"})
THRESHOLD_BY_CLAIM = {
    "HIGH": "high_max_z_q99",
    "LOW": "low_min_z_q01",
    "INCREASE": "increase_slope_q99",
    "REDUCTION": "reduction_slope_q01",
    "VARIABILITY": "high_variability_range_q99",
}
REQUIRED_METRICS = {
    "HIGH": ("max_z",),
    "LOW": ("min_z",),
    "INCREASE": ("slope_z_per_sample", "end_z", "start_z"),
    "REDUCTION": ("slope_z_per_sample", "end_z", "start_z"),
    "VARIABILITY": ("max_z", "min_z"),
}


class H3InputError(ValueError):
    """Raised when a response cannot be associated with a run or payload."""


@dataclass(frozen=True)
class EvidenceAudit:
    simulation_run: Any
    response_id: Any
    evidence_index: int
    variable: str | None
    claim: str | None
    observation: Any
    claim_valid: bool
    variable_allowed: bool
    variable_valid: bool
    variable_in_payload: bool
    threshold_available: bool
    threshold_name: str | None
    threshold_value: float | None
    start_z: float | None
    end_z: float | None
    min_z: float | None
    max_z: float | None
    slope_z_per_sample: float | None
    variability_range_rounded: float | None
    verifiable: bool
    rule_satisfied: bool
    item_score: int
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class H3ResponseEvaluation:
    simulation_run: Any
    response_id: Any
    decision: str
    evidence_items: int
    verifiable_items: int
    response_score: float | None
    audits: tuple[EvidenceAudit, ...]

    @property
    def applicable(self) -> bool:
        return self.response_score is not None

    def as_dict(self, *, include_audits: bool = False) -> dict[str, Any]:
        value = asdict(self)
        if include_audits:
            value["audits"] = [audit.as_dict() for audit in self.audits]
        else:
            value.pop("audits", None)
        return value


@dataclass(frozen=True)
class H3RunEvaluation:
    simulation_run: Any
    applicable_responses: int
    total_responses: int
    run_score: float | None
    response_scores: tuple[H3ResponseEvaluation, ...]
    audits: tuple[EvidenceAudit, ...]

    @property
    def applicable(self) -> bool:
        return self.run_score is not None

    def as_dict(
        self, *, include_responses: bool = False, include_audits: bool = False
    ) -> dict[str, Any]:
        value = asdict(self)
        if include_responses:
            value["response_scores"] = [
                response.as_dict(include_audits=False) for response in self.response_scores
            ]
        else:
            value.pop("response_scores", None)
        if include_audits:
            value["audits"] = [audit.as_dict() for audit in self.audits]
        else:
            value.pop("audits", None)
        return value


@dataclass(frozen=True)
class H3DatasetEvaluation:
    total_evidence_items: int
    verifiable_items: int
    coverage: float | None
    applicable_responses: int
    applicable_runs: int
    non_applicable_runs: int
    macro_mean: float | None
    median: float | None
    q1: float | None
    q3: float | None
    minimum: float | None
    maximum: float | None
    bootstrap_low: float | None
    bootstrap_high: float | None
    bootstrap_method: str | None
    bootstrap_resamples: int
    bootstrap_seed: int
    micro_score: float | None
    run_scores: tuple[H3RunEvaluation, ...]
    response_scores: tuple[H3ResponseEvaluation, ...]
    audits: tuple[EvidenceAudit, ...]

    def as_dict(self, *, include_details: bool = True) -> dict[str, Any]:
        value = asdict(self)
        if include_details:
            value["run_scores"] = [run.as_dict() for run in self.run_scores]
            value["response_scores"] = [
                response.as_dict() for response in self.response_scores
            ]
            value["audits"] = [audit.as_dict() for audit in self.audits]
        else:
            value.pop("run_scores", None)
            value.pop("response_scores", None)
            value.pop("audits", None)
        return value


def _normalise_decision(value: Any) -> str:
    return str(value if value is not None else "").strip().upper().replace("-", "_").replace(" ", "_")


def _normalise_claim(value: Any) -> str | None:
    if value is None:
        return None
    # Membership in the frozen enum is exact and case-sensitive.
    return str(value).strip()


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _mapping_value(mapping: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def _variable_payload(payload: Any, variable: str | None) -> Any:
    if variable is None:
        return None
    if isinstance(payload, Mapping):
        if variable in payload:
            return payload[variable]
        for namespace in (
            "variables",
            "variable_metrics",
            "features",
            "metrics",
            "payload",
            "window_payload",
        ):
            nested = payload.get(namespace)
            if isinstance(nested, Mapping) and variable in nested:
                return nested[variable]
            if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
                found = _variable_payload(nested, variable)
                if found is not None:
                    return found
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        for entry in payload:
            if not isinstance(entry, Mapping):
                continue
            name = _mapping_value(entry, ("variable", "name", "variable_name"))
            if str(name) == variable:
                return entry
    return None


def _metric(variable_payload: Any, name: str) -> float | None:
    if not isinstance(variable_payload, Mapping):
        return None
    if name in variable_payload:
        return _finite_float(variable_payload[name])
    for namespace in ("metrics", "summary", "statistics", "z_metrics"):
        nested = variable_payload.get(namespace)
        if isinstance(nested, Mapping) and name in nested:
            return _finite_float(nested[name])
    return None


def _unwrap_threshold(value: Any) -> float | None:
    if isinstance(value, Mapping):
        value = _mapping_value(value, ("value", "threshold", "cutoff"))
    return _finite_float(value)


def _threshold(
    thresholds: Mapping[str, Any], variable: str | None, threshold_name: str | None
) -> float | None:
    if variable is None or threshold_name is None:
        return None

    candidates: list[Any] = []
    direct_variable = thresholds.get(variable)
    if isinstance(direct_variable, Mapping):
        candidates.append(direct_variable.get(threshold_name))

    for namespace in ("variables", "by_variable", "thresholds"):
        nested = thresholds.get(namespace)
        if not isinstance(nested, Mapping):
            continue
        variable_block = nested.get(variable)
        if isinstance(variable_block, Mapping):
            candidates.append(variable_block.get(threshold_name))
        threshold_block = nested.get(threshold_name)
        if isinstance(threshold_block, Mapping):
            candidates.append(threshold_block.get(variable))
        elif threshold_block is not None:
            candidates.append(threshold_block)

    top_level = thresholds.get(threshold_name)
    if isinstance(top_level, Mapping):
        candidates.append(top_level.get(variable))
    elif top_level is not None:
        candidates.append(top_level)

    for candidate in candidates:
        parsed = _unwrap_threshold(candidate)
        if parsed is not None:
            return parsed
    return None


def _derive_valid_variables(thresholds: Mapping[str, Any]) -> set[str]:
    explicit = thresholds.get("valid_variables")
    if isinstance(explicit, Sequence) and not isinstance(explicit, (str, bytes)):
        return {str(value) for value in explicit}

    variables: set[str] = set()
    for namespace in (None, "variables", "by_variable"):
        block: Any = thresholds if namespace is None else thresholds.get(namespace)
        if not isinstance(block, Mapping):
            continue
        for key, value in block.items():
            if key in THRESHOLD_BY_CLAIM.values() or key in {
                "valid_variables",
                "thresholds",
            }:
                continue
            if isinstance(value, Mapping) and any(
                threshold_name in value
                for threshold_name in THRESHOLD_BY_CLAIM.values()
            ):
                variables.add(str(key))
    return variables


def _rule_satisfied(
    claim: str,
    variable_payload: Any,
    threshold_value: float,
) -> tuple[bool, str]:
    values = {
        metric: _metric(variable_payload, metric) for metric in REQUIRED_METRICS[claim]
    }
    missing = [metric for metric, value in values.items() if value is None]
    if missing:
        return False, "missing_or_nonfinite_metric:" + ",".join(missing)

    if claim == "HIGH":
        satisfied = values["max_z"] >= threshold_value  # type: ignore[operator]
    elif claim == "LOW":
        satisfied = values["min_z"] <= threshold_value  # type: ignore[operator]
    elif claim == "INCREASE":
        satisfied = (
            values["slope_z_per_sample"] >= threshold_value  # type: ignore[operator]
            and values["end_z"] > values["start_z"]  # type: ignore[operator]
        )
    elif claim == "REDUCTION":
        satisfied = (
            values["slope_z_per_sample"] <= threshold_value  # type: ignore[operator]
            and values["end_z"] < values["start_z"]  # type: ignore[operator]
        )
    else:
        # The four-decimal rounding is part of the frozen rule and occurs
        # before comparison with the reference threshold.
        observed_range = round(values["max_z"] - values["min_z"], 4)  # type: ignore[operator]
        satisfied = observed_range >= threshold_value
    return bool(satisfied), "rule_satisfied" if satisfied else "numeric_rule_not_satisfied"


def evaluate_evidence_item(
    item: Mapping[str, Any],
    payload: Any,
    thresholds: Mapping[str, Any],
    *,
    valid_variables: Iterable[str] | None = None,
    simulation_run: Any = None,
    response_id: Any = None,
    evidence_index: int = 0,
) -> EvidenceAudit:
    """Evaluate one evidence item and return its complete audit row."""

    variable_value = item.get("variable")
    variable = None if variable_value is None else str(variable_value)
    claim = _normalise_claim(item.get("claim"))
    # Stored for audit only.  No scoring branch reads this value.
    observation_for_audit = item.get("observation")

    allowed_variables = (
        {str(value) for value in valid_variables}
        if valid_variables is not None
        else _derive_valid_variables(thresholds)
    )
    claim_valid = claim in CLAIMS
    threshold_name = THRESHOLD_BY_CLAIM.get(claim) if claim_valid else None
    threshold_value = _threshold(thresholds, variable, threshold_name)
    variable_block = _variable_payload(payload, variable)
    variable_in_payload = variable_block is not None
    variable_allowed = variable is not None and variable in allowed_variables
    threshold_available = threshold_value is not None
    variable_valid = bool(variable_allowed and variable_in_payload and threshold_available)
    verifiable = bool(claim_valid and variable_valid)

    start_z = _metric(variable_block, "start_z")
    end_z = _metric(variable_block, "end_z")
    min_z = _metric(variable_block, "min_z")
    max_z = _metric(variable_block, "max_z")
    slope_z_per_sample = _metric(variable_block, "slope_z_per_sample")
    variability_range_rounded = (
        round(max_z - min_z, 4)
        if max_z is not None and min_z is not None
        else None
    )

    if not claim_valid:
        satisfied, reason = False, "unsupported_claim"
    elif not variable_allowed:
        satisfied, reason = False, "invalid_variable"
    elif not variable_in_payload:
        satisfied, reason = False, "variable_absent_from_same_window_payload"
    elif not threshold_available:
        satisfied, reason = False, "threshold_unavailable"
    else:
        satisfied, reason = _rule_satisfied(claim, variable_block, threshold_value)

    score = int(verifiable and satisfied)
    return EvidenceAudit(
        simulation_run=simulation_run,
        response_id=response_id,
        evidence_index=evidence_index,
        variable=variable,
        claim=claim,
        observation=observation_for_audit,
        claim_valid=claim_valid,
        variable_allowed=variable_allowed,
        variable_valid=variable_valid,
        variable_in_payload=variable_in_payload,
        threshold_available=threshold_available,
        threshold_name=threshold_name,
        threshold_value=threshold_value,
        start_z=start_z,
        end_z=end_z,
        min_z=min_z,
        max_z=max_z,
        slope_z_per_sample=slope_z_per_sample,
        variability_range_rounded=variability_range_rounded,
        verifiable=verifiable,
        rule_satisfied=satisfied,
        item_score=score,
        reason=reason,
    )


def _response_identity(response: Mapping[str, Any], fallback: int) -> Any:
    return _mapping_value(
        response,
        ("window_id", "windowId", "response_id", "sample_end", "sampleEnd"),
    ) if any(
        key in response
        for key in ("window_id", "windowId", "response_id", "sample_end", "sampleEnd")
    ) else fallback


def _response_payload(response: Mapping[str, Any]) -> Any:
    for name in (
        "llm_payload",
        "payload",
        "window_payload",
        "variable_payload",
        "evidence_reference",
        "feature_payload",
        "features",
        "metrics",
    ):
        if name in response:
            return response[name]
    return {}


def evaluate_h3_response(
    response: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    *,
    valid_variables: Iterable[str] | None = None,
    simulation_run: Any = None,
    response_index: int = 0,
) -> H3ResponseEvaluation:
    """Score one response, including the two frozen no-evidence cases."""

    if simulation_run is None:
        simulation_run = _mapping_value(
            response, ("simulationRun", "simulation_run", "run_id")
        )
    response_id = _response_identity(response, response_index)
    decision = _normalise_decision(
        _mapping_value(response, ("decision", "classification", "label"))
    )
    evidence_value = response.get("evidence")
    if evidence_value is None:
        evidence: list[Mapping[str, Any]] = []
    elif isinstance(evidence_value, Sequence) and not isinstance(
        evidence_value, (str, bytes)
    ):
        evidence = []
        for entry in evidence_value:
            evidence.append(entry if isinstance(entry, Mapping) else {})
    else:
        raise H3InputError("evidence must be a list or null")

    payload = _response_payload(response)
    audits = tuple(
        evaluate_evidence_item(
            item,
            payload,
            thresholds,
            valid_variables=valid_variables,
            simulation_run=simulation_run,
            response_id=response_id,
            evidence_index=index,
        )
        for index, item in enumerate(evidence)
    )

    if audits:
        response_score: float | None = statistics.fmean(
            audit.item_score for audit in audits
        )
    elif decision == "ANOMALY":
        response_score = 0.0
    else:
        # This covers NORMAL and EVIDENCE_INSUFFICIENT exactly as specified.
        # Unknown empty decisions are also non-applicable rather than silently
        # being treated as anomalous evidence failure.
        response_score = None

    return H3ResponseEvaluation(
        simulation_run=simulation_run,
        response_id=response_id,
        decision=decision,
        evidence_items=len(audits),
        verifiable_items=sum(audit.verifiable for audit in audits),
        response_score=response_score,
        audits=audits,
    )


def score_h3_run(
    responses: Iterable[Mapping[str, Any]],
    thresholds: Mapping[str, Any],
    *,
    valid_variables: Iterable[str] | None = None,
    simulation_run: Any = None,
) -> H3RunEvaluation:
    """Score one run as the mean of its applicable response scores."""

    materialised = list(responses)
    inferred_ids = {
        _mapping_value(response, ("simulationRun", "simulation_run", "run_id"))
        for response in materialised
        if _mapping_value(response, ("simulationRun", "simulation_run", "run_id"))
        is not None
    }
    if simulation_run is None:
        if len(inferred_ids) > 1:
            raise H3InputError("score_h3_run received responses from multiple runs")
        simulation_run = next(iter(inferred_ids), None)

    evaluations = tuple(
        evaluate_h3_response(
            response,
            thresholds,
            valid_variables=valid_variables,
            simulation_run=simulation_run,
            response_index=index,
        )
        for index, response in enumerate(materialised)
    )
    applicable = [
        response.response_score
        for response in evaluations
        if response.response_score is not None
    ]
    run_score = statistics.fmean(applicable) if applicable else None
    audits = tuple(audit for response in evaluations for audit in response.audits)
    return H3RunEvaluation(
        simulation_run=simulation_run,
        applicable_responses=len(applicable),
        total_responses=len(evaluations),
        run_score=run_score,
        response_scores=evaluations,
        audits=audits,
    )


def _quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _bootstrap_macro(
    run_scores: Sequence[float], resamples: int, seed: int
) -> tuple[float | None, float | None, str | None]:
    if not run_scores:
        return None, None, None
    if resamples < 1:
        raise H3InputError("bootstrap resamples must be at least 1")
    if len(run_scores) == 1:
        # The frozen SAP explicitly prohibits an inferential interval at n=1.
        return None, None, None
    generator = random.Random(seed)
    n = len(run_scores)
    draws = [
        statistics.fmean(run_scores[generator.randrange(n)] for _ in range(n))
        for _ in range(resamples)
    ]
    return (
        _quantile(draws, 0.025),
        _quantile(draws, 0.975),
        "percentile_run_level",
    )


def evaluate_h3_dataset(
    responses: Iterable[Mapping[str, Any]],
    thresholds: Mapping[str, Any],
    *,
    valid_variables: Iterable[str] | None = None,
    all_run_ids: Iterable[Any] | None = None,
    bootstrap_resamples: int = 10_000,
    bootstrap_seed: int = 20_260_820,
) -> H3DatasetEvaluation:
    """Evaluate H3 with equal run weight and return response/item audits."""

    grouped: dict[Any, list[Mapping[str, Any]]] = {}
    for response in responses:
        run_id = _mapping_value(
            response, ("simulationRun", "simulation_run", "run_id")
        )
        if run_id is None:
            raise H3InputError("every H3 response must identify simulationRun")
        grouped.setdefault(run_id, []).append(response)

    run_universe: list[Any] = []
    seen: set[Any] = set()
    if all_run_ids is not None:
        for run_id in all_run_ids:
            if run_id not in seen:
                seen.add(run_id)
                run_universe.append(run_id)
    for run_id in grouped:
        if run_id not in seen:
            seen.add(run_id)
            run_universe.append(run_id)

    runs = tuple(
        score_h3_run(
            grouped.get(run_id, []),
            thresholds,
            valid_variables=valid_variables,
            simulation_run=run_id,
        )
        for run_id in run_universe
    )
    response_scores = tuple(
        response for run in runs for response in run.response_scores
    )
    audits = tuple(audit for run in runs for audit in run.audits)
    applicable_run_values = [
        run.run_score for run in runs if run.run_score is not None
    ]
    item_scores = [audit.item_score for audit in audits]
    low, high, bootstrap_method = _bootstrap_macro(
        applicable_run_values, bootstrap_resamples, bootstrap_seed
    )

    return H3DatasetEvaluation(
        total_evidence_items=len(audits),
        verifiable_items=sum(audit.verifiable for audit in audits),
        coverage=(
            sum(audit.verifiable for audit in audits) / len(audits)
            if audits
            else None
        ),
        applicable_responses=sum(
            response.response_score is not None for response in response_scores
        ),
        applicable_runs=len(applicable_run_values),
        non_applicable_runs=len(runs) - len(applicable_run_values),
        macro_mean=(
            statistics.fmean(applicable_run_values)
            if applicable_run_values
            else None
        ),
        median=_quantile(applicable_run_values, 0.5),
        q1=_quantile(applicable_run_values, 0.25),
        q3=_quantile(applicable_run_values, 0.75),
        minimum=min(applicable_run_values) if applicable_run_values else None,
        maximum=max(applicable_run_values) if applicable_run_values else None,
        bootstrap_low=low,
        bootstrap_high=high,
        bootstrap_method=bootstrap_method,
        bootstrap_resamples=bootstrap_resamples,
        bootstrap_seed=bootstrap_seed,
        micro_score=(statistics.fmean(item_scores) if item_scores else None),
        run_scores=runs,
        response_scores=response_scores,
        audits=audits,
    )


def score_evidence_item(*args: Any, **kwargs: Any) -> int:
    """Convenience wrapper returning only the binary item score."""

    return evaluate_evidence_item(*args, **kwargs).item_score


def score_h3_response(*args: Any, **kwargs: Any) -> float | None:
    """Convenience wrapper returning only the response score."""

    return evaluate_h3_response(*args, **kwargs).response_score


__all__ = [
    "CLAIMS",
    "EvidenceAudit",
    "H3DatasetEvaluation",
    "H3InputError",
    "H3ResponseEvaluation",
    "H3RunEvaluation",
    "evaluate_evidence_item",
    "evaluate_h3_dataset",
    "evaluate_h3_response",
    "score_evidence_item",
    "score_h3_response",
    "score_h3_run",
]
