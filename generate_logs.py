"""Generate the two probe log files.

Each file is 20,000 lines of repetitive agent noise plus one rare
critical signal at the end. Generation is deterministic.

Case 1 (retry_storm): the rare CRITICAL line is structurally distinct from
the WARN retry noise, like a real webhook failure surfacing in a retry loop.

Case 2 (tool_needle): the rare ERROR line is structurally identical to the
INFO noise (same field layout, different level and values), like a payment
failure that looks like every other tool call on the outside.
"""

from pathlib import Path

NOISE_COUNT = 20_000
LOGS_DIR = Path(__file__).resolve().parent / "logs"

RETRY_CRITICAL = (
    "2026-08-13T10:00:15Z CRITICAL agent step=9001 tool=billing_webhook "
    "retry=0 status=failed error=signature_mismatch event_id=CRITICAL_NEEDLE_8f3a"
)

TOOL_ERROR = (
    "2026-08-13T10:00:15Z ERROR tool=payments status=failed "
    "error=signature_mismatch attempt=19999 event_id=TOOL_NEEDLE_2c9d"
)


def retry_storm_lines() -> list[str]:
    lines = []
    for i in range(1, NOISE_COUNT + 1):
        lines.append(
            f"2026-08-13T10:00:00Z WARN agent step={i} tool=search_web "
            f"retry={i} after=5000ms err=rate_limited"
        )
    lines.append(RETRY_CRITICAL)
    return lines


def tool_needle_lines() -> list[str]:
    lines = []
    for i in range(1, NOISE_COUNT + 1):
        tool = "payments" if i % 2 == 0 else "gateway"
        lines.append(
            f"2026-08-13T10:00:00Z INFO tool={tool} status=ok "
            f"error=none attempt={i}"
        )
    lines.append(TOOL_ERROR)
    return lines


def main() -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    for name, lines in (
        ("retry_storm.log", retry_storm_lines()),
        ("tool_needle.log", tool_needle_lines()),
    ):
        (LOGS_DIR / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {NOISE_COUNT + 1} lines each to {LOGS_DIR}")


if __name__ == "__main__":
    main()