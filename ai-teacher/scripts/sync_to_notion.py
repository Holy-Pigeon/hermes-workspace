#!/usr/bin/env python3
"""Sync an AI Teacher Markdown lesson into a dedicated Notion database."""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / ".openclaw" / "notion_ai_teacher.json"
OPENCLAW_CONFIG = Path.home() / ".openclaw" / "openclaw.json"
DEFAULT_PARENT_PAGE_ID = "2f6d8689-fc19-8110-9ab8-df82d320e860"
NOTION_VERSION = "2022-06-28"
LANGUAGE_ALIASES = {
    "": "plain text",
    "text": "plain text",
    "txt": "plain text",
    "py": "python",
    "sh": "shell",
    "zsh": "shell",
}


def load_token() -> str:
    token = os.environ.get("NOTION_API_TOKEN")
    if token:
        return token

    if OPENCLAW_CONFIG.exists():
        data = json.loads(OPENCLAW_CONFIG.read_text())
        token = (
            data.get("skills", {})
            .get("entries", {})
            .get("notion", {})
            .get("apiKey")
        )
        if token:
            return token

    raise RuntimeError("Missing Notion token. Set NOTION_API_TOKEN or configure skills.entries.notion.apiKey.")


def notion_request(method: str, path: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        f"https://api.notion.com/v1/{path.lstrip('/')}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )

    last_error: Exception | None = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            # 429 / 5xx are transient — retry; other HTTP errors are fatal
            if exc.code in (429, 500, 502, 503, 504) and attempt < 4:
                last_error = exc
                time.sleep(2.0 * (attempt + 1))
                continue
            raise RuntimeError(f"Notion API {method} {path} failed: HTTP {exc.code} {detail}") from exc
        except (urllib.error.URLError, ssl.SSLError, EOFError, ConnectionError, OSError) as exc:
            last_error = exc
            if attempt == 4:
                break
            time.sleep(2.0 * (attempt + 1))

    raise RuntimeError(last_error or f"Notion API {method} {path} failed with unknown network error")


def load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {
        "parent_page_id": DEFAULT_PARENT_PAGE_ID,
        "database_id": None,
        "database_title": "AI Teacher｜Transformer 深度学习课",
    }


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")


def ensure_database(token: str, config: dict[str, Any]) -> dict[str, Any]:
    database_id = config.get("database_id")
    if database_id:
        try:
            return notion_request("GET", f"databases/{database_id}", token)
        except RuntimeError as exc:
            # Only treat a genuine 404 (database deleted/missing) as "needs recreation".
            # Transient errors (SSL EOF, 5xx, network) must NOT silently spawn a new
            # database — that scatters lessons across orphan DBs. Re-raise instead.
            msg = str(exc)
            if "HTTP 404" not in msg:
                raise
            config["database_id"] = None

    title = config.get("database_title") or "AI Teacher｜Transformer 深度学习课"
    parent_page_id = config.get("parent_page_id") or DEFAULT_PARENT_PAGE_ID
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": {
            "Name": {"title": {}},
            "Topic": {"rich_text": {}},
            "Category": {"select": {}},
            "Stage": {"select": {}},
            "Lesson Date": {"date": {}},
            "Difficulty": {"select": {}},
            "Status": {"select": {}},
            "Source": {"rich_text": {}},
            "Discord Message": {"url": {}},
        },
    }
    database = notion_request("POST", "databases", token, payload)
    config["database_id"] = database["id"]
    save_config(config)
    return database


def rich_text(text: str) -> list[dict[str, Any]]:
    """Convert text to Notion rich_text array, handling inline LaTeX $...$ as equation annotations."""
    parts: list[dict[str, Any]] = []
    # Split on inline math $...$ (but not $$...$$)
    pattern = re.compile(r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)')
    last_end = 0
    for m in pattern.finditer(text):
        # Text before the math
        before = text[last_end:m.start()]
        if before:
            for chunk in textwrap.wrap(before, 1800, replace_whitespace=False, drop_whitespace=False) or [""]:
                parts.append({"type": "text", "text": {"content": chunk}})
        # The inline equation
        expr = m.group(1).strip()
        parts.append({"type": "equation", "equation": {"expression": expr}})
        last_end = m.end()
    # Remaining text after last match
    remaining = text[last_end:]
    if remaining:
        for chunk in textwrap.wrap(remaining, 1800, replace_whitespace=False, drop_whitespace=False) or [""]:
            parts.append({"type": "text", "text": {"content": chunk}})
    if not parts:
        parts.append({"type": "text", "text": {"content": ""}})
    return parts[:100]


def paragraph(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text)}}


def heading(level: int, text: str) -> dict[str, Any]:
    key = f"heading_{min(max(level, 1), 3)}"
    return {"object": "block", "type": key, key: {"rich_text": rich_text(text)}}


def bullet(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rich_text(text)}}


def numbered(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "numbered_list_item", "numbered_list_item": {"rich_text": rich_text(text)}}


def code_block(code: str, language: str = "plain text") -> dict[str, Any]:
    language = LANGUAGE_ALIASES.get(language.lower(), language.lower())
    return {
        "object": "block",
        "type": "code",
        "code": {"rich_text": rich_text(code[:1900]), "language": language},
    }


def markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    in_code = False
    code_lang = "plain text"
    code_lines: list[str] = []
    para_lines: list[str] = []

    def flush_para() -> None:
        if para_lines:
            blocks.append(paragraph(" ".join(line.strip() for line in para_lines).strip()))
            para_lines.clear()

    # First pass: merge $$ block equations into single lines
    merged_lines: list[str] = []
    in_equation = False
    eq_lines: list[str] = []
    for raw in markdown.splitlines():
        stripped = raw.strip()
        if stripped == "$$" and not in_equation:
            in_equation = True
            eq_lines = []
            continue
        elif stripped == "$$" and in_equation:
            in_equation = False
            merged_lines.append("$$" + " ".join(eq_lines) + "$$")
            continue
        if in_equation:
            eq_lines.append(stripped)
            continue
        merged_lines.append(raw)

    for raw in merged_lines:
        line = raw.rstrip()
        # Block equation $$...$$
        eq_match = re.match(r"^\$\$(.+)\$\$$", line.strip())
        if eq_match and not in_code:
            flush_para()
            blocks.append({
                "object": "block",
                "type": "equation",
                "equation": {"expression": eq_match.group(1).strip()},
            })
            continue

        fence = re.match(r"^```(\w+)?", line)
        if fence:
            if in_code:
                blocks.append(code_block("\n".join(code_lines), code_lang))
                code_lines.clear()
                code_lang = "plain text"
                in_code = False
            else:
                flush_para()
                in_code = True
                code_lang = fence.group(1) or "plain text"
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not line.strip():
            flush_para()
            continue

        heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading_match:
            flush_para()
            blocks.append(heading(len(heading_match.group(1)), heading_match.group(2).strip()))
            continue

        bullet_match = re.match(r"^[-*]\s+(.+)$", line)
        if bullet_match:
            flush_para()
            blocks.append(bullet(bullet_match.group(1).strip()))
            continue

        numbered_match = re.match(r"^\d+\.\s+(.+)$", line)
        if numbered_match:
            flush_para()
            blocks.append(numbered(numbered_match.group(1).strip()))
            continue

        if line.strip() == "---":
            flush_para()
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            continue

        para_lines.append(line)

    if in_code and code_lines:
        blocks.append(code_block("\n".join(code_lines), code_lang))
    flush_para()
    return blocks


def chunks(items: list[dict[str, Any]], size: int = 90) -> list[list[dict[str, Any]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def page_url(page_id: str) -> str:
    return f"https://www.notion.so/{page_id.replace('-', '')}"


def archive_existing_pages(token: str, database_id: str, topic_title: str) -> int:
    """Archive any existing pages in the DB whose Name matches topic_title (idempotent upsert)."""
    archived = 0
    payload = {
        "filter": {"property": "Name", "title": {"equals": topic_title}},
        "page_size": 100,
    }
    try:
        result = notion_request("POST", f"databases/{database_id}/query", token, payload)
    except RuntimeError:
        return 0
    for page in result.get("results", []):
        try:
            notion_request("PATCH", f"pages/{page['id']}", token, {"archived": True})
            archived += 1
        except RuntimeError:
            pass
    return archived


def create_lesson_page(args: argparse.Namespace) -> dict[str, Any]:
    token = load_token()
    config = load_config()
    database = ensure_database(token, config)
    markdown = Path(args.file).read_text()
    blocks = markdown_to_blocks(markdown)

    archived = 0
    if not getattr(args, "no_upsert", False):
        archived = archive_existing_pages(token, database["id"], args.title)

    properties: dict[str, Any] = {
        "Name": {"title": [{"type": "text", "text": {"content": args.title}}]},
        "Topic": {"rich_text": [{"type": "text", "text": {"content": args.topic or args.title}}]},
        "Status": {"select": {"name": args.status}},
        "Source": {"rich_text": [{"type": "text", "text": {"content": "ai-teacher"}}]},
    }
    if args.category:
        properties["Category"] = {"select": {"name": args.category[:100]}}
    if args.stage:
        properties["Stage"] = {"select": {"name": args.stage[:100]}}
    if args.lesson_date:
        properties["Lesson Date"] = {"date": {"start": args.lesson_date}}
    if args.difficulty:
        properties["Difficulty"] = {"select": {"name": args.difficulty[:100]}}

    page = notion_request(
        "POST",
        "pages",
        token,
        {"parent": {"database_id": database["id"]}, "properties": properties},
    )
    for batch in chunks(blocks):
        notion_request("PATCH", f"blocks/{page['id']}/children", token, {"children": batch})

    result = {
        "page_id": page["id"],
        "url": page.get("url") or page_url(page["id"]),
        "database_id": database["id"],
        "database_title": config.get("database_title"),
        "blocks": len(blocks),
        "archived_old": archived,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ensure-db", action="store_true", help="Create or verify the dedicated Notion database.")
    parser.add_argument("--file", help="Markdown lesson file to sync.")
    parser.add_argument("--title", help="Lesson title.")
    parser.add_argument("--topic", default="")
    parser.add_argument("--category", default="")
    parser.add_argument("--stage", default="")
    parser.add_argument("--lesson-date", default="")
    parser.add_argument("--difficulty", default="")
    parser.add_argument("--status", default="Published")
    parser.add_argument("--no-upsert", action="store_true",
                        help="Skip archiving existing pages with the same title (default: upsert on).")
    args = parser.parse_args()

    token = load_token()
    config = load_config()
    if args.ensure_db:
        database = ensure_database(token, config)
        print(json.dumps({"database_id": database["id"], "url": database.get("url")}, ensure_ascii=False))
        return 0

    if not args.file or not args.title:
        parser.error("--file and --title are required unless --ensure-db is used")

    result = create_lesson_page(args)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
