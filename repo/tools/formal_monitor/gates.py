from tep_local.governance import (
    CONFORMANCE_FILE,
    METHOD_FREEZE_ID,
    GateReport,
    inspect_static_gates,
    main,
    require_real_start,
)

__all__ = [
    "CONFORMANCE_FILE",
    "METHOD_FREEZE_ID",
    "GateReport",
    "inspect_static_gates",
    "main",
    "require_real_start",
]


if __name__ == "__main__":
    raise SystemExit(main())
