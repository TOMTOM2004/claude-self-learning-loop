#!/usr/bin/env python3
"""
PostToolUse(Bash) hook: tracks pytest errors in real-time.

For each Bash call during the session:
- If pytest output contains FAILED/ERROR  → appends error entry to state file (status: "pending")
- If pytest output shows all tests passed → marks all pending entries as "resolved"

State file: /tmp/claude_pending_lessons_{session_id}.json
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path


# Patterns for pytest output detection
RE_FAILED_LINE = re.compile(r"FAILED\s+(\S+)")
RE_ERROR_LINE = re.compile(r"ERROR\s+(\S+)")
RE_ERROR_TYPE = re.compile(r"(\w+Error|\w+Exception|AssertionError|TypeError|ValueError|ImportError|KeyError|AttributeError)")
RE_PASSED_ALL = re.compile(r"\d+ passed")
RE_STILL_FAILED = re.compile(r"\bFAILED\b")
RE_SHORT_SUMMARY = re.compile(r"FAILED [^\n]+|ERROR [^\n]+")


def get_state_file(session_id: str) -> Path:
    return Path(f"/tmp/claude_pending_lessons_{session_id}.json")


def load_state(state_file: Path, session_id: str) -> dict:
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except Exception:
            pass
    return {"session_id": session_id, "errors": []}


def save_state(state_file: Path, state: dict) -> None:
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def extract_error_signature(failed_tests: list[str]) -> str:
    """Stable signature to avoid duplicate entries for the same test failures."""
    return "|".join(sorted(failed_tests[:5]))


def main():
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    # Only process Bash tool results
    if hook_input.get("tool_name") != "Bash":
        sys.exit(0)

    tool_result = hook_input.get("tool_result", "")
    if not isinstance(tool_result, str) or not tool_result:
        sys.exit(0)

    # Quick pre-filter: skip if not pytest-related output
    if "passed" not in tool_result and "FAILED" not in tool_result and "ERROR" not in tool_result:
        sys.exit(0)

    session_id = hook_input.get("session_id", "unknown")
    state_file = get_state_file(session_id)
    state = load_state(state_file, session_id)

    failed_tests = RE_FAILED_LINE.findall(tool_result)
    error_tests = RE_ERROR_LINE.findall(tool_result)
    all_failing = failed_tests + error_tests

    if all_failing:
        # ── FAILURES detected ──────────────────────────────────────────────
        signature = extract_error_signature(all_failing)
        existing_sigs = {e["error_signature"] for e in state["errors"]}

        if signature not in existing_sigs:
            # Extract the short-summary lines (most readable part of pytest output)
            summary_lines = RE_SHORT_SUMMARY.findall(tool_result)[:5]

            # Best-effort error type extraction
            error_type_match = RE_ERROR_TYPE.search(tool_result)
            error_type = error_type_match.group(1) if error_type_match else "TestFailure"

            test_command = ""
            tool_input = hook_input.get("tool_input", {})
            if isinstance(tool_input, dict):
                test_command = tool_input.get("command", "")
            elif isinstance(tool_input, str):
                test_command = tool_input

            state["errors"].append({
                "id": f"err_{len(state['errors'])}_{datetime.now().strftime('%H%M%S')}",
                "timestamp": datetime.now().isoformat(),
                "error_type": error_type,
                "failed_tests": all_failing[:5],
                "summary_lines": summary_lines,
                "test_command": test_command[:200],  # truncate long commands
                "error_signature": signature,
                "status": "pending",
            })
            save_state(state_file, state)

    elif RE_PASSED_ALL.search(tool_result) and not RE_STILL_FAILED.search(tool_result):
        # ── ALL TESTS PASSED ───────────────────────────────────────────────
        changed = False
        for error in state["errors"]:
            if error["status"] == "pending":
                error["status"] = "resolved"
                error["resolved_at"] = datetime.now().isoformat()
                changed = True
        if changed:
            save_state(state_file, state)

    sys.exit(0)


if __name__ == "__main__":
    main()
