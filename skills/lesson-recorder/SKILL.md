---
name: lesson-recorder
description: This skill should be used when pytest or tests were FAILED and then PASSED during this session, or when asked to "record a lesson", "save error fix", "save lesson", "save what was learned", "教訓を保存", "学習を記録". Performs noise filtering, autonomous root cause analysis (5 Whys), distills to concise 3-sentence format, deduplicates, and saves structured lesson to the memory MCP server. Handles multiple errors in one session.
allowed-tools: Read, Grep, Bash, mcp__memory__save_lesson, mcp__memory__search_lessons
---

# Lesson Recorder

This skill extracts high-quality, distilled lessons from error resolution and saves them to long-term memory.
Follow these steps carefully.

---

## Multiple Errors Handling

If the systemMessage or ARGUMENTS lists **multiple errors**, process them **one by one** from first to last.
For each error, run Steps 0–5 independently. Do not skip any error.
After all errors are processed, provide a summary of all saved (and skipped) lessons.

---

## Step 0: Noise Filter — Is This Worth Saving?

Before doing anything, judge whether this error resolution is worth recording.

**Skip (do NOT save) if:**
- The error was a simple typo or indentation issue fixed in under 1 minute
- The same test was re-run without any code changes
- The failure was environment-specific (port conflict, network timeout, missing env var)
- The error is already well-documented (e.g., standard `ModuleNotFoundError` from missing `pip install`)

**Save if:**
- The fix required understanding a non-obvious code pattern or API behavior
- Multiple attempts were needed before finding the right solution
- The root cause reveals a systemic issue (missing guard clause, wrong data type assumption, etc.)
- The fix pattern is reusable for similar problems

If the error does not qualify, respond: "This error was too trivial to save as a lesson. No action taken."

---

## Step 1: Extract Error Information (Structured, Not Raw)

From the conversation transcript:

1. Identify the **first failing test output** (the FAILED/ERROR markers)
2. Extract:
   - **Error type**: e.g., `TypeError`, `AssertionError`, `ImportError`
   - **Error message**: the key line, NOT the full stack trace
   - **Failing test name** (optional context)
3. Identify the **code change** that fixed it:
   - Which file was modified?
   - What was the key change? (1-2 lines, not the full diff)

**Do NOT include**: full stack traces, line numbers, file paths (unless semantically meaningful)

---

## Step 1.5: Read State File (if available)

If a session state file path was provided in the systemMessage (e.g., `/tmp/claude_pending_lessons_*.json`), run:
```bash
cat /tmp/claude_pending_lessons_<session_id>.json
```
This gives the list of all errors tracked during the verification phase. Use these entries to cross-reference with the transcript for more accurate extraction.

---

## Step 2: Autonomous Root Cause Analysis (5 Whys)

Use Read and Grep tools to investigate the code and identify the true root cause.

Work through these questions:
1. **Why did the test fail?** (direct technical reason)
2. **Why was the code written that way?** (design assumption or missing guard)
3. **Why wasn't this caught earlier?** (test coverage gap, wrong assumption)
4. **Are there similar patterns elsewhere?** — Use `Grep` to search for the same pattern in other files

Document your analysis. The root cause should explain WHY, not just WHAT.

Reference: [references/rca-methodology.md](references/rca-methodology.md)

---

## Step 3: Distill to 3-Sentence Format

Compress all your analysis into the template below. Each field must be **exactly 1 concise sentence**.

```
Error: [What type of error occurred and in what context — no stack traces]
Cause: [The root cause — the WHY, systemic or design issue]
Fix: [The reusable solution pattern — how to prevent this class of error]
```

**Good example:**
```
Error: AsyncIO event loop was already running when synchronous DB call was made inside an async endpoint.
Cause: The database client was initialized with a synchronous connection pool, incompatible with the async FastAPI context.
Fix: Use async-compatible DB client (asyncpg/SQLAlchemy async) or wrap sync calls with asyncio.run_in_executor().
```

**Bad example (too verbose / raw):**
```
Error: File "app/db.py", line 42, in connect — RuntimeError: This event loop is already running
Cause: It failed because we called connect() which is blocking
Fix: I changed line 42 to use await
```

---

## Step 4: Deduplication Check

Before saving, search for similar existing lessons to avoid duplicates.

Call `mcp__memory__search_lessons` with a query describing the error type and context.

- If a **highly similar lesson** (similarity > 0.85) exists: evaluate whether the new lesson adds genuinely new information
  - If not: respond "A very similar lesson already exists. No duplicate saved."
  - If yes (new angle, different fix): proceed to save
- If no similar lesson found: proceed to save

---

## Step 5: Save the Lesson

Call `mcp__memory__save_lesson` with these parameters:

```
error_summary: [your 1-sentence error description from Step 3]
root_cause:    [your 1-sentence root cause from Step 3]
solution:      [your 1-sentence fix pattern from Step 3]
tags:          [list: error_type + affected_layer, e.g. ["TypeError", "async", "database"]]
project:       [current project name/path, or empty string]
```

After saving, confirm: "✅ Lesson saved to memory. Future sessions will benefit from this lesson when encountering similar errors."

---

## Output Summary

After completing all steps, briefly summarize what was learned and saved (2-3 sentences max).
