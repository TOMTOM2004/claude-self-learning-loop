#!/usr/bin/env python3
"""
Stop hook (command-based): checks state file for unsaved resolved errors.

Decision logic:
  1. Load /tmp/claude_pending_lessons_{session_id}.json
  2. Find errors that are resolved but not yet saved
  3. Check if save_lesson was already called this session (via transcript)
  4. If unsaved resolved errors exist → block with systemMessage listing all errors
  5. Otherwise → approve

This replaces the prompt-based Stop hook for more deterministic, multi-error handling.
"""

import json
import sys
from pathlib import Path


def get_state_file(session_id: str) -> Path:
    return Path(f"/tmp/claude_pending_lessons_{session_id}.json")


def was_lesson_saved_this_session(transcript_path: str) -> bool:
    """Check if save_lesson MCP tool was already called by scanning the transcript."""
    if not transcript_path:
        return False
    tp = Path(transcript_path)
    if not tp.exists():
        return False
    try:
        content = tp.read_text(errors="ignore")
        return "save_lesson" in content
    except Exception:
        return False


def main():
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        print(json.dumps({"decision": "approve"}))
        sys.exit(0)

    session_id = hook_input.get("session_id", "unknown")
    transcript_path = hook_input.get("transcript_path", "")

    state_file = get_state_file(session_id)

    # ── No state file: no pytest was tracked this session ──────────────────
    if not state_file.exists():
        print(json.dumps({"decision": "approve"}))
        sys.exit(0)

    try:
        state = json.loads(state_file.read_text())
    except Exception:
        print(json.dumps({"decision": "approve"}))
        sys.exit(0)

    # ── Find resolved but not-yet-saved errors ──────────────────────────────
    resolved_errors = [e for e in state.get("errors", []) if e["status"] == "resolved"]

    if not resolved_errors:
        print(json.dumps({"decision": "approve"}))
        sys.exit(0)

    # ── If save_lesson was already called this session, approve ─────────────
    if was_lesson_saved_this_session(transcript_path):
        print(json.dumps({"decision": "approve"}))
        sys.exit(0)

    # ── Block and list all errors that need saving ──────────────────────────
    error_blocks = []
    for i, err in enumerate(resolved_errors):
        tests = ", ".join(err.get("failed_tests", [])[:3])
        summaries = "\n    ".join(err.get("summary_lines", [])[:2])
        timestamp = err.get("timestamp", "")[:16].replace("T", " ")
        error_blocks.append(
            f"Error {i + 1} [{err.get('error_type', '?')}] @ {timestamp}\n"
            f"  Tests: {tests or '(unknown)'}\n"
            f"  Summary: {summaries or '(see transcript)'}"
        )

    errors_text = "\n\n".join(error_blocks)
    count = len(resolved_errors)

    system_msg = (
        f"このセッション中に {count} 件のテストエラーが解決されました。"
        f"停止する前に lesson-recorder スキルを使って、各エラーの教訓を長期メモリに保存してください。\n\n"
        f"【解決済みエラー一覧】\n{errors_text}\n\n"
        f"lesson-recorder スキルを実行し、上記の各エラーについて Step 0〜5 を適用してください。"
        f"複数エラーがある場合は、各エラーを個別に処理してください。"
    )

    output = {
        "decision": "block",
        "reason": f"{count} 件の解決済みエラーをメモリに保存してから停止してください。",
        "systemMessage": system_msg,
    }
    print(json.dumps(output, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
