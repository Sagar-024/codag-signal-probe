"""Verify whether rare critical signals survive codag-drain compression.

The recovery mechanism being tested is the one codag-drain actually
publishes in its `--format json` output (verified from its CLI source and
the codag.ai homepage example):

  - each template group keeps up to 3 raw member lines as samples, each
    carrying its 0-based input index (`samples[].index`);
  - each group exposes its first member's index (`first_index`);
  - a template collapses all its members, so a member that is only covered
    by `count` (never sampled, never first) is not individually citable.

A rare signal is judged RECOVERED only when its source index is cited and
its exact content (the needle) is present in the compressed artifact.
"""

import json
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent / "logs"
OUT_DIR = Path(__file__).resolve().parent / "out"

SIGNALS = {
    "retry_storm": {
        "needle": "CRITICAL_NEEDLE_8f3a",
        "error": "error=signature_mismatch",
        "status": "status=failed",
        "tool": "tool=billing_webhook",
        "level": "critical",
    },
    "tool_needle": {
        "needle": "TOOL_NEEDLE_2c9d",
        "error": "error=signature_mismatch",
        "status": "status=failed",
        "level": "error",
    },
}


def load_lines(case: str) -> list[str]:
    return (LOGS_DIR / f"{case}.log").read_text(encoding="utf-8").splitlines()


def load_result(case: str) -> dict:
    return json.loads((OUT_DIR / f"{case}.codag.json").read_text(encoding="utf-8"))


def rare_line_index(lines: list[str], needle: str, case: str) -> int:
    for i, line in enumerate(lines):
        if needle in line:
            return i
    raise ValueError(f"needle not found in {case}: {needle}")


def cited_indexes(result: dict) -> set[int]:
    cited: set[int] = set()
    for group in result["groups"]:
        cited.add(int(group["first_index"]))
        for sample in group["samples"]:
            cited.add(int(sample["index"]))
    return cited


def artifact_text(result: dict) -> str:
    parts: list[str] = []
    for group in result["groups"]:
        parts.append(group["template"])
        for sample in group["samples"]:
            parts.append(sample["text"])
            if sample.get("level"):
                parts.append(sample["level"])
            if sample.get("timestamp"):
                parts.append(sample["timestamp"])
        for slot in group["slots"]:
            parts.extend(slot["samples"])
    return "\n".join(parts)


def report_case(case: str) -> None:
    lines = load_lines(case)
    result = load_result(case)
    idx = rare_line_index(lines, SIGNALS[case]["needle"], case)
    cited = cited_indexes(result)

    groups = result["groups"]
    own_group = any(
        int(group["count"]) == 1
        and any(int(sample["index"]) == idx for sample in group["samples"])
        for group in groups
    )

    text = artifact_text(result)
    signals = SIGNALS[case]
    recovered = [name for name, sub in signals.items() if sub in text]
    lost = [name for name, sub in signals.items() if sub not in text]

    if signals["needle"] in text and idx in cited:
        verdict = "RECOVERED"
    elif signals["needle"] in text:
        verdict = "PARTIAL"
    else:
        verdict = "LOST"

    original_bytes = len("\n".join(lines).encode("utf-8"))
    compressed_bytes = len(json.dumps(result).encode("utf-8"))
    template_count = int(result["template_count"])

    print(f"case: {case}")
    print(f"original size: {original_bytes} bytes / {len(lines)} lines")
    print(f"compressed size: {compressed_bytes} bytes / {template_count} groups")
    print(f"compression: {len(lines) / template_count:.0f}x lines, "
          f"{original_bytes / compressed_bytes:.0f}x bytes")
    print("recovery mechanism: group membership + per-group sample line indexes "
          "(samples[].index / first_index) in codag-drain --format json")
    print(f"rare line index cited: {idx in cited} (line 1-based {idx + 1})")
    print(f"rare line kept as own group: {own_group}")
    print(f"recovered signals: {', '.join(recovered) or 'none'}")
    print(f"lost signals: {', '.join(lost) or 'none'}")
    print(f"final observation: {verdict}")


if __name__ == "__main__":
    for case in sorted(SIGNALS):
        report_case(case)
        print()