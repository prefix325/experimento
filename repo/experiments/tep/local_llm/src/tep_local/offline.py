from __future__ import annotations

import json
import socket
import urllib.request
from pathlib import Path


def verify_network_none(output_path: str | Path) -> dict:
    dns_failed = False
    https_failed = False
    dns_error = None
    https_error = None

    try:
        socket.getaddrinfo("example.com", 443)
    except Exception as exc:  # expected under --network none
        dns_failed = True
        dns_error = f"{type(exc).__name__}: {exc}"

    try:
        with urllib.request.urlopen("https://example.com", timeout=3) as response:
            response.read(1)
    except Exception as exc:  # expected under --network none
        https_failed = True
        https_error = f"{type(exc).__name__}: {exc}"

    result = {
        "dns_resolution_failed": dns_failed,
        "external_https_failed": https_failed,
        "dns_error": dns_error,
        "https_error": https_error,
        "network_none_verified": dns_failed and https_failed,
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not result["network_none_verified"]:
        raise RuntimeError("External network access was unexpectedly available")
    return result


def verify_mount_permissions(read_only_paths: list[str | Path], writable_path: str | Path) -> dict:
    checks = []
    for root in map(Path, read_only_paths):
        probe = root / ".psqza_write_probe"
        blocked = False
        error = None
        try:
            probe.write_text("must not be writable", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError as exc:
            blocked = True
            error = f"{type(exc).__name__}: {exc}"
        checks.append({"path": str(root), "expected": "read_only", "blocked": blocked, "error": error})
        if not blocked:
            raise RuntimeError(f"Expected read-only mount is writable: {root}")

    writable_root = Path(writable_path)
    writable_root.mkdir(parents=True, exist_ok=True)
    probe = writable_root / ".psqza_write_probe"
    probe.write_text("writable", encoding="utf-8")
    probe.unlink()
    checks.append({"path": str(writable_root), "expected": "writable", "writable": True})
    return {"checks": checks, "all_ok": True}
