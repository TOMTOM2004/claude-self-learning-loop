#!/usr/bin/env python3
"""
UserPromptSubmit hook: Semantic search of past lessons and inject as systemMessage.
Runs directly (no MCP round-trip) for low latency.
"""

import json
import sys
from pathlib import Path

DB_PATH = str(Path(__file__).parent / "data")
OLLAMA_BASE_URL = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"
MIN_SIMILARITY = 0.45
MAX_RESULTS = 3
MIN_PROMPT_LENGTH = 15


def get_embedding(text: str) -> list[float] | None:
    try:
        import httpx
        response = httpx.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
            timeout=5.0,
        )
        response.raise_for_status()
        return response.json()["embedding"]
    except Exception:
        return None


def main():
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, Exception):
        sys.exit(0)

    user_prompt = hook_input.get("user_prompt", "")
    if not user_prompt or len(user_prompt) < MIN_PROMPT_LENGTH:
        sys.exit(0)

    # Get embedding for query
    embedding = get_embedding(user_prompt)
    if not embedding:
        # Ollama unavailable - transparent pass-through
        sys.exit(0)

    try:
        import chromadb

        client = chromadb.PersistentClient(path=DB_PATH)
        try:
            collection = client.get_collection("lessons")
        except Exception:
            # Collection doesn't exist yet
            sys.exit(0)

        if collection.count() == 0:
            sys.exit(0)

        results = collection.query(
            query_embeddings=[embedding],
            n_results=min(MAX_RESULTS, collection.count()),
            include=["metadatas", "distances"],
        )

        lessons = []
        for i, meta in enumerate(results["metadatas"][0]):
            distance = results["distances"][0][i]
            similarity = 1.0 - distance / 2.0
            if similarity < MIN_SIMILARITY:
                continue
            lessons.append(
                f"• [{meta.get('tags', '[]')}] {meta['error_summary']} → {meta['solution']}"
            )

        if lessons:
            system_msg = "**📚 過去の関連教訓（自動検索）:**\n" + "\n".join(lessons)
            output = {"systemMessage": system_msg}
            print(json.dumps(output, ensure_ascii=False))

    except Exception:
        # Any error: transparent pass-through (don't block user)
        sys.exit(0)


if __name__ == "__main__":
    main()
