"""Independent reconstruction of the frozen LLM and DPCA endpoints.

This module deliberately works from primary, row-like records.  It has no
dependency on detector aggregation code and it does not perform statistical
aggregation while traversing records.  The returned dataclasses are suitable
for materialising a run-level table first.

The three LLM evaluation regions are explicit:

``target_post``
    ``sample_end >= onset``.
``target_pre``
    ``sample_end <= onset - 1``.
``normal_full``
    the complete observed trajectory.

Filtering happens before candidates are paired.  Consequently, a candidate
on one side of the target onset can never be confirmed on the other side.
Every anomalous window is evaluated independently at ``window_id + R``;
candidate failure never clears another candidate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable, Mapping, Sequence


ONSET_SAMPLE = 161
LLM_CONFIRMATION_LAG = 4
DPCA_PERSISTENCE = 3
MINUTES_PER_SAMPLE = 3


class EndpointInputError(ValueError):
    """Raised when primary records cannot define an unambiguous endpoint."""


class EndpointIntegrityError(RuntimeError):
    """Raised when an independently reconstructed flag disagrees with native data."""


@dataclass(frozen=True)
class LLMEndpoint:
    """One LLM endpoint reconstructed for one run and one evaluation region."""

    region: str
    raw: bool
    confirmed: bool
    no_confirmation: bool
    first_raw_window_id: int | None
    first_raw_sample_end: int | None
    first_confirmed_candidate_window_id: int | None
    first_confirmation_window_id: int | None
    first_confirmation_sample_end: int | None
    raw_delay_minutes: int | None
    confirmed_delay_minutes: int | None
    anomaly_window_ids: tuple[int, ...]
    confirmed_candidate_window_ids: tuple[int, ...]

    @property
    def raw_detected(self) -> bool:
        return self.raw

    @property
    def confirmed_detected(self) -> bool:
        return self.confirmed

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["anomaly_window_ids"] = list(self.anomaly_window_ids)
        value["confirmed_candidate_window_ids"] = list(
            self.confirmed_candidate_window_ids
        )
        return value


@dataclass(frozen=True)
class DPCASampleFlag:
    """Reconstructed DPCA state at a single sample."""

    sample: int
    alarm_raw: bool
    alarm_persistent: bool
    persisted_alarm_persistent: bool | None
    native_flag_comparable: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DPCAEndpoint:
    """One DPCA endpoint reconstructed for one run and one sample interval."""

    first_sample: int | None
    last_sample: int | None
    reset: bool
    persistence: int
    raw: bool
    confirmed: bool
    no_confirmation: bool
    first_raw_sample: int | None
    first_persistent_sample: int | None
    raw_delay_minutes: int | None
    confirmed_delay_minutes: int | None
    sample_flags: tuple[DPCASampleFlag, ...]

    @property
    def raw_detected(self) -> bool:
        return self.raw

    @property
    def confirmed_detected(self) -> bool:
        return self.confirmed

    def as_dict(self, *, include_sample_flags: bool = False) -> dict[str, Any]:
        value = asdict(self)
        if include_sample_flags:
            value["sample_flags"] = [row.as_dict() for row in self.sample_flags]
        else:
            value.pop("sample_flags", None)
        return value


@dataclass(frozen=True)
class NativeFlagCrosscheck:
    """Result of comparing independently reconstructed and stored flags."""

    label: str
    status: str
    compared: int
    skipped: int
    mismatch_count: int
    mismatches: tuple[dict[str, Any], ...]

    @property
    def passed(self) -> bool:
        return self.status in {"PASS", "NOT_APPLICABLE"}

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mismatches"] = list(self.mismatches)
        return value


def _value(record: Mapping[str, Any], names: Sequence[str], *, required: bool) -> Any:
    for name in names:
        if name in record:
            return record[name]
    if required:
        raise EndpointInputError(f"missing required field; expected one of {tuple(names)!r}")
    return None


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise EndpointInputError(f"{label} must be an integer, not bool")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        try:
            parsed = int(stripped)
        except ValueError as exc:
            raise EndpointInputError(f"{label} is not an integer: {value!r}") from exc
        return parsed
    raise EndpointInputError(f"{label} is not an integer: {value!r}")


def _boolean(value: Any, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalised = value.strip().upper()
        if normalised in {"TRUE", "T", "YES", "Y", "1"}:
            return True
        if normalised in {"FALSE", "F", "NO", "N", "0"}:
            return False
    raise EndpointInputError(f"{label} is not a boolean: {value!r}")


def _optional_boolean(record: Mapping[str, Any], names: Sequence[str]) -> bool | None:
    value = _value(record, names, required=False)
    if value is None:
        return None
    return _boolean(value, names[0])


def _normalise_llm_region(region: str) -> str:
    aliases = {
        "target_post": "target_post",
        "target_post_onset": "target_post",
        "post_onset": "target_post",
        "target_pre": "target_pre",
        "target_pre_onset": "target_pre",
        "pre_onset": "target_pre",
        "normal_full": "normal_full",
        "normal": "normal_full",
        "full": "normal_full",
    }
    try:
        return aliases[str(region).strip().lower()]
    except KeyError as exc:
        raise EndpointInputError(
            "region must be 'target_post', 'target_pre', or 'normal_full'"
        ) from exc


def _in_llm_region(sample_end: int, region: str, onset: int) -> bool:
    if region == "target_post":
        return sample_end >= onset
    if region == "target_pre":
        return sample_end <= onset - 1
    return True


def _eligible(record: Mapping[str, Any]) -> bool:
    marker = _value(
        record,
        ("eligible", "decision_eligible", "is_eligible", "eligible_for_detection"),
        required=False,
    )
    return True if marker is None else _boolean(marker, "eligible")


def _is_anomaly(record: Mapping[str, Any]) -> bool:
    if not _eligible(record):
        return False
    decision = _value(record, ("decision", "classification", "label"), required=True)
    return str(decision).strip().upper() == "ANOMALY"


def delay_minutes(
    detected: bool,
    detection_sample: int | None,
    *,
    origin_sample: int = ONSET_SAMPLE,
    minutes_per_sample: int = MINUTES_PER_SAMPLE,
) -> int | None:
    """Return a frozen-SAP delay, preserving non-detection as ``None``."""

    if not detected:
        return None
    if detection_sample is None:
        raise EndpointInputError("a detected endpoint must have a detection sample")
    return (int(detection_sample) - int(origin_sample)) * int(minutes_per_sample)


def reconstruct_llm_endpoint(
    records: Iterable[Mapping[str, Any]],
    region: str,
    onset: int = ONSET_SAMPLE,
    R: int = LLM_CONFIRMATION_LAG,
) -> LLMEndpoint:
    """Reconstruct a run-level LLM endpoint using exact ``k -> k + R`` pairing.

    ``records`` must contain one logical row per ``window_id`` with a decision
    and ``sample_end``.  Duplicate window identifiers are rejected because an
    arbitrary duplicate choice would invalidate the blind reconstruction.
    """

    canonical_region = _normalise_llm_region(region)
    onset = _integer(onset, "onset")
    R = _integer(R, "R")
    if R < 1:
        raise EndpointInputError("R must be at least 1")

    windows: dict[int, tuple[int, bool]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise EndpointInputError("each LLM record must be a mapping")
        window_id = _integer(
            _value(record, ("window_id", "windowId", "window"), required=True),
            "window_id",
        )
        if window_id in windows:
            raise EndpointInputError(f"duplicate LLM window_id: {window_id}")
        sample_end = _integer(
            _value(record, ("sample_end", "sampleEnd", "end_sample"), required=True),
            "sample_end",
        )
        windows[window_id] = (sample_end, _is_anomaly(record))

    # The region restriction precedes pairing.  This is the onset reset and is
    # what prevents a pre-onset candidate from being confirmed post-onset.
    regional = {
        window_id: values
        for window_id, values in windows.items()
        if _in_llm_region(values[0], canonical_region, onset)
    }
    anomaly_ids = tuple(sorted(w for w, (_, anomaly) in regional.items() if anomaly))

    confirmed_candidates: list[int] = []
    for candidate_id in anomaly_ids:
        confirmation = regional.get(candidate_id + R)
        if confirmation is not None and confirmation[1]:
            confirmed_candidates.append(candidate_id)

    raw = bool(anomaly_ids)
    confirmed = bool(confirmed_candidates)

    if raw:
        first_raw_window = min(anomaly_ids, key=lambda w: (regional[w][0], w))
        first_raw_sample = regional[first_raw_window][0]
    else:
        first_raw_window = None
        first_raw_sample = None

    if confirmed:
        first_candidate = min(
            confirmed_candidates,
            key=lambda w: (regional[w + R][0], w + R, w),
        )
        first_confirmation_window = first_candidate + R
        first_confirmation_sample = regional[first_confirmation_window][0]
    else:
        first_candidate = None
        first_confirmation_window = None
        first_confirmation_sample = None

    use_delay = canonical_region == "target_post"
    return LLMEndpoint(
        region=canonical_region,
        raw=raw,
        confirmed=confirmed,
        no_confirmation=not confirmed,
        first_raw_window_id=first_raw_window,
        first_raw_sample_end=first_raw_sample,
        first_confirmed_candidate_window_id=first_candidate,
        first_confirmation_window_id=first_confirmation_window,
        first_confirmation_sample_end=first_confirmation_sample,
        raw_delay_minutes=(
            delay_minutes(raw, first_raw_sample, origin_sample=onset) if use_delay else None
        ),
        confirmed_delay_minutes=(
            delay_minutes(confirmed, first_confirmation_sample, origin_sample=onset)
            if use_delay
            else None
        ),
        anomaly_window_ids=anomaly_ids,
        confirmed_candidate_window_ids=tuple(confirmed_candidates),
    )


def _prepare_dpca_records(
    records: Iterable[Mapping[str, Any]],
) -> dict[int, tuple[bool, bool | None]]:
    prepared: dict[int, tuple[bool, bool | None]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise EndpointInputError("each DPCA record must be a mapping")
        sample = _integer(_value(record, ("sample",), required=True), "sample")
        if sample in prepared:
            raise EndpointInputError(f"duplicate DPCA sample: {sample}")
        raw = _boolean(
            _value(record, ("alarm_raw", "raw_alarm"), required=True), "alarm_raw"
        )
        native = _optional_boolean(
            record, ("alarm_persistent", "persistent_alarm", "alarm_confirmed")
        )
        prepared[sample] = (raw, native)
    return prepared


def _bounded(sample: int, first_sample: int | None, last_sample: int | None) -> bool:
    return (first_sample is None or sample >= first_sample) and (
        last_sample is None or sample <= last_sample
    )


def reconstruct_dpca_persistence(
    records: Iterable[Mapping[str, Any]],
    first_sample: int | None = None,
    last_sample: int | None = None,
    reset: bool = True,
    persistence: int = DPCA_PERSISTENCE,
) -> tuple[DPCASampleFlag, ...]:
    """Reconstruct raw-to-persistent DPCA state within a scientific region.

    Persistence requires ``persistence`` raw alarms at consecutive integer
    samples.  A false alarm or a sample gap clears the streak.  With ``reset``
    true, records before ``first_sample`` cannot contribute state.
    """

    if first_sample is not None:
        first_sample = _integer(first_sample, "first_sample")
    if last_sample is not None:
        last_sample = _integer(last_sample, "last_sample")
    persistence = _integer(persistence, "persistence")
    if persistence < 1:
        raise EndpointInputError("persistence must be at least 1")
    if first_sample is not None and last_sample is not None and first_sample > last_sample:
        raise EndpointInputError("first_sample must not exceed last_sample")

    prepared = _prepare_dpca_records(records)
    ordered_samples = sorted(prepared)
    if reset:
        state_samples = [
            sample
            for sample in ordered_samples
            if _bounded(sample, first_sample, last_sample)
        ]
    else:
        # Carry-in is allowed only from actual supplied primary rows.  Rows
        # after the requested interval are unnecessary for endpoint state.
        state_samples = [
            sample
            for sample in ordered_samples
            if last_sample is None or sample <= last_sample
        ]

    output: list[DPCASampleFlag] = []
    streak = 0
    previous_sample: int | None = None
    streak_samples: list[int] = []
    for sample in state_samples:
        raw, native = prepared[sample]
        if raw:
            if previous_sample is not None and sample == previous_sample + 1:
                streak += 1
                streak_samples.append(sample)
            else:
                streak = 1
                streak_samples = [sample]
        else:
            streak = 0
            streak_samples = []

        persistent_flag = streak >= persistence
        previous_sample = sample

        if not _bounded(sample, first_sample, last_sample):
            continue

        # With no scientific reset, every supplied native flag is comparable.
        # After a reset, only the first p-1 samples can legitimately differ
        # because the persisted native field may contain pre-boundary carry-in.
        comparable = (
            not reset
            or first_sample is None
            or sample >= first_sample + persistence - 1
        )

        output.append(
            DPCASampleFlag(
                sample=sample,
                alarm_raw=raw,
                alarm_persistent=persistent_flag,
                persisted_alarm_persistent=native,
                native_flag_comparable=comparable,
            )
        )

    return tuple(output)


def reconstruct_dpca_endpoint(
    records: Iterable[Mapping[str, Any]],
    first_sample: int | None,
    last_sample: int | None,
    reset: bool = True,
    *,
    persistence: int = DPCA_PERSISTENCE,
    onset: int = ONSET_SAMPLE,
) -> DPCAEndpoint:
    """Reconstruct the DPCA raw and persistence-3 run endpoints.

    Delay is defined only for a post-onset interval whose ``first_sample`` is
    ``onset``.  In all other regions it is returned as ``None``.
    """

    flags = reconstruct_dpca_persistence(
        records,
        first_sample=first_sample,
        last_sample=last_sample,
        reset=reset,
        persistence=persistence,
    )
    raw_samples = [row.sample for row in flags if row.alarm_raw]
    persistent_samples = [row.sample for row in flags if row.alarm_persistent]
    first_raw = min(raw_samples) if raw_samples else None
    first_persistent = min(persistent_samples) if persistent_samples else None
    raw = first_raw is not None
    confirmed = first_persistent is not None
    post_onset = first_sample is not None and int(first_sample) == int(onset)

    return DPCAEndpoint(
        first_sample=first_sample,
        last_sample=last_sample,
        reset=bool(reset),
        persistence=int(persistence),
        raw=raw,
        confirmed=confirmed,
        no_confirmation=not confirmed,
        first_raw_sample=first_raw,
        first_persistent_sample=first_persistent,
        raw_delay_minutes=(
            delay_minutes(raw, first_raw, origin_sample=onset) if post_onset else None
        ),
        confirmed_delay_minutes=(
            delay_minutes(confirmed, first_persistent, origin_sample=onset)
            if post_onset
            else None
        ),
        sample_flags=flags,
    )


def _finish_crosscheck(
    *,
    label: str,
    compared: int,
    skipped: int,
    mismatches: list[dict[str, Any]],
    raise_on_mismatch: bool,
) -> NativeFlagCrosscheck:
    if compared == 0:
        status = "NOT_APPLICABLE"
    elif mismatches:
        status = "FAIL"
    else:
        status = "PASS"
    result = NativeFlagCrosscheck(
        label=label,
        status=status,
        compared=compared,
        skipped=skipped,
        mismatch_count=len(mismatches),
        mismatches=tuple(mismatches),
    )
    if mismatches and raise_on_mismatch:
        raise EndpointIntegrityError(
            f"{label}: {len(mismatches)} reconstructed/native flag mismatch(es)"
        )
    return result


def crosscheck_native_flags(
    records: Iterable[Mapping[str, Any]],
    first_sample: int | None = 1,
    last_sample: int | None = None,
    reset: bool = True,
    *,
    persistence: int = DPCA_PERSISTENCE,
    raise_on_mismatch: bool = True,
) -> NativeFlagCrosscheck:
    """Cross-check stored DPCA persistence flags where semantics are comparable."""

    flags = reconstruct_dpca_persistence(
        records,
        first_sample=first_sample,
        last_sample=last_sample,
        reset=reset,
        persistence=persistence,
    )
    mismatches: list[dict[str, Any]] = []
    compared = 0
    skipped = 0
    for row in flags:
        if row.persisted_alarm_persistent is None or not row.native_flag_comparable:
            skipped += 1
            continue
        compared += 1
        if row.alarm_persistent != row.persisted_alarm_persistent:
            mismatches.append(
                {
                    "sample": row.sample,
                    "reconstructed": row.alarm_persistent,
                    "native": row.persisted_alarm_persistent,
                }
            )
    return _finish_crosscheck(
        label="DPCA alarm_persistent",
        compared=compared,
        skipped=skipped,
        mismatches=mismatches,
        raise_on_mismatch=raise_on_mismatch,
    )


def crosscheck_endpoint_flag(
    reconstructed: bool,
    native: bool | int | str | None,
    *,
    label: str = "endpoint",
    raise_on_mismatch: bool = True,
) -> NativeFlagCrosscheck:
    """Cross-check one reconstructed run endpoint against an explicit native flag.

    Callers must extract the exact contracted field from ``detection_summary``;
    this function intentionally does not guess among similarly named fields.
    """

    if native is None:
        return _finish_crosscheck(
            label=label,
            compared=0,
            skipped=1,
            mismatches=[],
            raise_on_mismatch=raise_on_mismatch,
        )
    native_bool = _boolean(native, f"native {label}")
    mismatch = bool(reconstructed) != native_bool
    mismatches = (
        [{"key": label, "reconstructed": bool(reconstructed), "native": native_bool}]
        if mismatch
        else []
    )
    return _finish_crosscheck(
        label=label,
        compared=1,
        skipped=0,
        mismatches=mismatches,
        raise_on_mismatch=raise_on_mismatch,
    )


def calculate_run_level_endpoints(
    *,
    cohort: str,
    simulation_run: int | str,
    blind_run_id: str,
    llm_records: Iterable[Mapping[str, Any]] | None = None,
    dpca_records: Iterable[Mapping[str, Any]] | None = None,
    last_sample: int | None = None,
    onset: int = ONSET_SAMPLE,
) -> dict[str, Any]:
    """Build a flat, serialisable endpoint row for later aggregation."""

    cohort_name = str(cohort).strip()
    upper = cohort_name.upper()
    if "TARGET" in upper:
        llm_region = "target_post"
        dpca_first = onset
    elif "NORMAL" in upper:
        llm_region = "normal_full"
        dpca_first = 1
    else:
        raise EndpointInputError("cohort must identify TARGET or NORMAL")

    row: dict[str, Any] = {
        "blind_run_id": blind_run_id,
        "simulationRun": simulation_run,
        "cohort": cohort_name,
    }

    if llm_records is not None:
        materialised_llm = list(llm_records)
        llm = reconstruct_llm_endpoint(materialised_llm, llm_region, onset=onset)
        row.update(
            {
                "llm_raw": llm.raw,
                "llm_confirmed": llm.confirmed,
                "llm_no_confirmation": llm.no_confirmation,
                "llm_first_raw_window_id": llm.first_raw_window_id,
                "llm_first_raw_sample_end": llm.first_raw_sample_end,
                "llm_first_confirmation_window_id": llm.first_confirmation_window_id,
                "llm_first_confirmation_sample_end": llm.first_confirmation_sample_end,
                "llm_raw_delay_minutes": llm.raw_delay_minutes,
                "llm_confirmed_delay_minutes": llm.confirmed_delay_minutes,
            }
        )
        if "TARGET" in upper:
            pre = reconstruct_llm_endpoint(materialised_llm, "target_pre", onset=onset)
            row.update(
                {
                    "llm_prefault_raw": pre.raw,
                    "llm_prefault_confirmed": pre.confirmed,
                }
            )

    if dpca_records is not None:
        materialised_dpca = list(dpca_records)
        dpca = reconstruct_dpca_endpoint(
            materialised_dpca,
            first_sample=dpca_first,
            last_sample=last_sample,
            reset=True,
            onset=onset,
        )
        row.update(
            {
                "dpca_raw": dpca.raw,
                "dpca_confirmed": dpca.confirmed,
                "dpca_no_confirmation": dpca.no_confirmation,
                "dpca_first_raw_sample": dpca.first_raw_sample,
                "dpca_first_persistent_sample": dpca.first_persistent_sample,
                "dpca_raw_delay_minutes": dpca.raw_delay_minutes,
                "dpca_confirmed_delay_minutes": dpca.confirmed_delay_minutes,
            }
        )
        if "TARGET" in upper:
            pre = reconstruct_dpca_endpoint(
                materialised_dpca,
                first_sample=1,
                last_sample=onset - 1,
                reset=True,
                onset=onset,
            )
            row.update(
                {
                    "dpca_prefault_raw": pre.raw,
                    "dpca_prefault_confirmed": pre.confirmed,
                }
            )
    return row


# Descriptive aliases make the independent implementation convenient to call
# from a runner without importing detector terminology.
calculate_llm_endpoint = reconstruct_llm_endpoint
calculate_dpca_endpoint = reconstruct_dpca_endpoint


__all__ = [
    "DPCAEndpoint",
    "DPCASampleFlag",
    "EndpointInputError",
    "EndpointIntegrityError",
    "LLMEndpoint",
    "NativeFlagCrosscheck",
    "calculate_dpca_endpoint",
    "calculate_llm_endpoint",
    "calculate_run_level_endpoints",
    "crosscheck_endpoint_flag",
    "crosscheck_native_flags",
    "delay_minutes",
    "reconstruct_dpca_endpoint",
    "reconstruct_dpca_persistence",
    "reconstruct_llm_endpoint",
]
