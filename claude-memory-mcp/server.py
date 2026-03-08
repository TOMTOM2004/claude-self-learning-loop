#!/usr/bin/env python3
"""
Claude Memory MCP Server
Saves and retrieves lessons learned from error resolution.
Uses Ollama (nomic-embed-text) for embeddings and ChromaDB for storage.
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import chromadb
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Paths
DB_PATH = str(Path(__file__).parent / "data")
OLLAMA_BASE_URL = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"

app = Server("memory")

# Initialize ChromaDB client (lazy)
_chroma_client = None
_collection = None


def get_collection():
    global _chroma_client, _collection
    if _collection is None:
        _chroma_client = chromadb.PersistentClient(path=DB_PATH)
        _collection = _chroma_client.get_or_create_collection(
            name="lessons",
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def get_embedding(text: str) -> list[float]:
    """Embed text using Ollama nomic-embed-text."""
    try:
        response = httpx.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
            timeout=15.0,
        )
        response.raise_for_status()
        return response.json()["embedding"]
    except Exception as e:
        raise RuntimeError(f"Embedding failed: {e}") from e


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="save_lesson",
            description=(
                "Save a lesson learned from error resolution. "
                "Use this after fixing tests to record the error pattern, root cause, and solution. "
                "Input should be pre-distilled (concise, 1 sentence per field)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "error_summary": {
                        "type": "string",
                        "description": "1-sentence description of the error (distilled, no raw stack traces)",
                    },
                    "root_cause": {
                        "type": "string",
                        "description": "1-sentence root cause (the WHY, not just WHAT failed)",
                    },
                    "solution": {
                        "type": "string",
                        "description": "1-sentence solution pattern (reusable fix approach)",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Error category tags (e.g. ['TypeError', 'async', 'API'])",
                    },
                    "project": {
                        "type": "string",
                        "description": "Project name or path (optional)",
                    },
                },
                "required": ["error_summary", "root_cause", "solution"],
            },
        ),
        Tool(
            name="search_lessons",
            description="Search for relevant past lessons using semantic similarity. Returns the most relevant past error resolutions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language query describing the current problem or error",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 5)",
                        "default": 5,
                    },
                    "min_similarity": {
                        "type": "number",
                        "description": "Minimum similarity threshold 0.0-1.0 (default: 0.3)",
                        "default": 0.3,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="list_lessons",
            description="List the most recently saved lessons.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of lessons to return (default: 10)",
                        "default": 10,
                    },
                },
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "save_lesson":
        return await _save_lesson(arguments)
    elif name == "search_lessons":
        return await _search_lessons(arguments)
    elif name == "list_lessons":
        return await _list_lessons(arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")


async def _save_lesson(args: dict) -> list[TextContent]:
    error_summary = args["error_summary"]
    root_cause = args["root_cause"]
    solution = args["solution"]
    tags = args.get("tags", [])
    project = args.get("project", "")

    # Combine for embedding
    combined_text = f"Error: {error_summary} Cause: {root_cause} Fix: {solution}"

    embedding = get_embedding(combined_text)

    doc_id = f"lesson_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    metadata = {
        "error_summary": error_summary,
        "root_cause": root_cause,
        "solution": solution,
        "tags": json.dumps(tags),
        "project": project,
        "saved_at": datetime.now().isoformat(),
    }

    collection = get_collection()
    collection.add(
        ids=[doc_id],
        embeddings=[embedding],
        documents=[combined_text],
        metadatas=[metadata],
    )

    return [
        TextContent(
            type="text",
            text=(
                f"✅ Lesson saved (ID: {doc_id})\n"
                f"Error: {error_summary}\n"
                f"Root cause: {root_cause}\n"
                f"Solution: {solution}"
            ),
        )
    ]


async def _search_lessons(args: dict) -> list[TextContent]:
    query = args["query"]
    limit = args.get("limit", 5)
    min_similarity = args.get("min_similarity", 0.3)

    collection = get_collection()
    if collection.count() == 0:
        return [TextContent(type="text", text="No lessons saved yet.")]

    query_embedding = get_embedding(query)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(limit, collection.count()),
        include=["metadatas", "distances"],
    )

    lessons = []
    for i, meta in enumerate(results["metadatas"][0]):
        distance = results["distances"][0][i]
        # ChromaDB cosine distance: 0 = identical, 2 = opposite
        # Convert to similarity: 1 - distance/2
        similarity = 1.0 - distance / 2.0
        if similarity < min_similarity:
            continue
        saved_at = meta.get("saved_at", "")[:10]
        tags = json.loads(meta.get("tags", "[]"))
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        project = meta.get("project", "")
        proj_str = f" ({project})" if project else ""

        lessons.append(
            f"**Lesson {i + 1}**{tag_str}{proj_str} — saved {saved_at} (similarity: {similarity:.2f})\n"
            f"  Error: {meta['error_summary']}\n"
            f"  Cause: {meta['root_cause']}\n"
            f"  Fix: {meta['solution']}"
        )

    if not lessons:
        return [TextContent(type="text", text="No relevant lessons found for this query.")]

    return [TextContent(type="text", text="\n\n".join(lessons))]


async def _list_lessons(args: dict) -> list[TextContent]:
    limit = args.get("limit", 10)

    collection = get_collection()
    total = collection.count()
    if total == 0:
        return [TextContent(type="text", text="No lessons saved yet.")]

    # Get all and sort by saved_at (newest first)
    all_results = collection.get(include=["metadatas"])
    items = sorted(
        zip(all_results["ids"], all_results["metadatas"]),
        key=lambda x: x[1].get("saved_at", ""),
        reverse=True,
    )[:limit]

    lines = [f"**Recent lessons** (showing {len(items)} of {total} total)\n"]
    for doc_id, meta in items:
        saved_at = meta.get("saved_at", "")[:16].replace("T", " ")
        tags = json.loads(meta.get("tags", "[]"))
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        lines.append(
            f"• {saved_at}{tag_str}: {meta['error_summary']}"
        )

    return [TextContent(type="text", text="\n".join(lines))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
