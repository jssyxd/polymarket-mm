"""Hourly report writer and reader.

A report is Markdown with three fixed sections (Metrics, Decision, State)
so an operator can read one file and know everything the monitor did. The
sanitized payload rides along inside an HTML comment so
:func:`read_reports` can recover the same numbers without a second file.

No credential ever reaches a report. Keys that look like secrets are
dropped before anything is written.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

__all__ = ["write_report", "read_reports", "sanitize"]

_MARKER_START = "<!-- pmm-payload"
_MARKER_END = "-->"
_REPORT_GLOB = ".md"
_REPORT_WINDOW_SECONDS = 24 * 3600

_CREDENTIAL_PATTERNS = (
    "secret",
    "passphrase",
    "private",
    "api_key",
    "apikey",
    "api-key",
    "credential",
    "password",
    "passwd",
    "signature",
    "token",
    "cookie",
    "session",
)


def _is_credential(key: str) -> bool:
    lowered = key.lower()
    if lowered.endswith("_id") or lowered.endswith("_ids"):
        return False
    return any(pattern in lowered for pattern in _CREDENTIAL_PATTERNS)


def sanitize(value):
    """Drop anything that looks like a credential, recursively."""
    if isinstance(value, dict):
        return {
            key: sanitize(item)
            for key, item in value.items()
            if not _is_credential(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    return value


def _format(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (list, tuple)):
        if not value:
            return "-"
        return ", ".join(_format(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _table(rows: dict) -> list[str]:
    if not rows:
        return ["- none -"]
    lines = ["| field | value |", "| --- | --- |"]
    for key, value in rows.items():
        lines.append(f"| {key} | {_format(value)} |")
    return lines


def _render(payload: dict) -> str:
    metrics = payload.get("metrics") or {}
    decision = payload.get("decision") or {}
    state = payload.get("state") or {}
    timestamp = payload.get("timestamp") or datetime.now(timezone.utc).isoformat()

    lines = ["# Polymarket maker hourly monitor report", ""]
    lines.append(f"Generated: {timestamp}")
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    lines.extend(_table(metrics))
    lines.append("")
    lines.append("## Decision")
    lines.append("")
    lines.extend(
        _table(
            {
                "changed": decision.get("changed"),
                "action": decision.get("action"),
                "param": decision.get("param"),
                "from_value": decision.get("from_value"),
                "to_value": decision.get("to_value"),
                "reason": decision.get("reason"),
            }
        )
    )
    lines.append("")
    lines.append("## State")
    lines.append("")
    lines.extend(_table(state))
    lines.append("")
    lines.append(_MARKER_START)
    lines.append(json.dumps(sanitize(payload), sort_keys=True, default=str))
    lines.append(_MARKER_END)
    lines.append("")
    return "\n".join(lines)


def write_report(path: str, payload: dict) -> str:
    """Write one hourly report as Markdown and return the path written."""
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    body = _render(sanitize(dict(payload or {})))
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return path


def _extract_payload(text: str) -> dict:
    start = text.find(_MARKER_START)
    if start < 0:
        return {}
    start = text.find("\n", start)
    end = text.find(_MARKER_END, start if start > 0 else 0)
    if start < 0 or end < 0:
        return {}
    raw = text[start + 1 : end].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_timestamp(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return float(text)
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    return None


def read_reports(directory: str) -> list[dict]:
    """Read back the reports written in the last 24 hours, newest first."""
    if not os.path.isdir(directory):
        return []
    cutoff = datetime.now(timezone.utc).timestamp() - _REPORT_WINDOW_SECONDS
    reports: list[dict] = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(_REPORT_GLOB):
            continue
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            continue
        payload = _extract_payload(text)
        stamp = _parse_timestamp(payload.get("timestamp"))
        if stamp is None:
            stamp = os.path.getmtime(path)
        if stamp < cutoff:
            continue
        payload["path"] = path
        payload["timestamp"] = payload.get("timestamp") or stamp
        reports.append(payload)
    reports.sort(
        key=lambda item: _parse_timestamp(item.get("timestamp")) or 0.0,
        reverse=True,
    )
    return reports
