#!/usr/bin/env python3
"""
PreToolUse hook for Claude Code.
Sends unapproved tool calls to Slack for interactive approval.
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

load_dotenv(Path(__file__).parent / ".env")

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]

APPROVAL_DIR = Path("/tmp/claude_approvals")
TIMEOUT_SECONDS = 300
POLL_INTERVAL = 0.5

ALLOW_PATTERNS = [
    ("Bash", ["python ", "pip ", "git "]),
    ("Read", None),
    ("mcp__memory__save_lesson", None),
    ("mcp__memory__search_lessons", None),
    ("mcp__memory__list_lessons", None),
]


def is_allowed(tool_name: str, tool_input: dict) -> bool:
    for allowed_tool, prefixes in ALLOW_PATTERNS:
        if tool_name != allowed_tool:
            continue
        if prefixes is None:
            return True
        command = tool_input.get("command", "")
        for prefix in prefixes:
            if command.startswith(prefix):
                return True
    return False


def send_slack_approval_request(client, request_id, tool_name, tool_input):
    params_json = json.dumps(tool_input, ensure_ascii=False, indent=2)
    if len(params_json) > 1500:
        params_json = params_json[:1497] + "..."
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "Claude Code 承認リクエスト", "emoji": True}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*ツール:*\n`{tool_name}`"},
            {"type": "mrkdwn", "text": f"*リクエストID:*\n`{request_id}`"},
        ]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*パラメータ:*\n```{params_json}```"}},
        {"type": "actions", "block_id": request_id, "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "✅ 承認", "emoji": True},
             "style": "primary", "action_id": "approve", "value": request_id},
            {"type": "button", "text": {"type": "plain_text", "text": "❌ 拒否", "emoji": True},
             "style": "danger", "action_id": "deny", "value": request_id},
        ]},
    ]
    response = client.chat_postMessage(channel=SLACK_CHANNEL_ID, blocks=blocks,
                                       text=f"Claude Code承認リクエスト: {tool_name}")
    return response["ts"]


def wait_for_result(request_id: str) -> str:
    result_path = APPROVAL_DIR / f"{request_id}.result"
    deadline = time.time() + TIMEOUT_SECONDS
    while time.time() < deadline:
        if result_path.exists():
            result = result_path.read_text().strip()
            result_path.unlink(missing_ok=True)
            return result
        time.sleep(POLL_INTERVAL)
    return "timeout"


def main():
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Failed to parse hook input: {e}", file=sys.stderr)
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    if is_allowed(tool_name, tool_input):
        sys.exit(0)

    APPROVAL_DIR.mkdir(parents=True, exist_ok=True)
    request_id = str(uuid.uuid4())[:8]
    client = WebClient(token=SLACK_BOT_TOKEN)

    try:
        send_slack_approval_request(client, request_id, tool_name, tool_input)
    except SlackApiError as e:
        print(f"Slack API error: {e}", file=sys.stderr)
        sys.exit(2)

    result = wait_for_result(request_id)

    if result == "approve":
        sys.exit(0)
    elif result == "timeout":
        print(json.dumps({"decision": "block", "reason": "Slack承認がタイムアウトしました（300秒）"}, ensure_ascii=False))
        sys.exit(2)
    else:
        print(json.dumps({"decision": "block", "reason": "Slackで拒否されました"}, ensure_ascii=False))
        sys.exit(2)


if __name__ == "__main__":
    main()
