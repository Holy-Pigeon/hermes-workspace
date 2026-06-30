#!/usr/bin/env python3
"""Sync a Quant-Systems-Curriculum Markdown lesson into a dedicated Notion database."""

from __future__ import annotations

import argparse
import json
import mimetypes
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
CONFIG_PATH = ROOT / ".openclaw" / "notion_quant_curriculum.json"
OPENCLAW_CONFIG = Path.home() / ".openclaw" / "openclaw.json"
DEFAULT_PARENT_PAGE_ID = "2f6d8689-fc19-8110-9ab8-df82d320e860"
NOTION_VERSION = "2022-06-28"

# Notion API 境外站，方案B精细化分流下命令行/cron 默认不走代理 → 偶发 SSL EOF。
# 优先读环境变量代理，否则 fallback 本机 Clash 混合端口 7897；NOTION_NO_PROXY=1 可强制直连。
_PROXY = (
    os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    or os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY")
    or ("" if os.environ.get("NOTION_NO_PROXY") else "http://127.0.0.1:7897")
)
_opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": _PROXY, "https": _PROXY}) if _PROXY
    else urllib.request.ProxyHandler({})
)

LANGUAGE_ALIASES = {
    "": "plain text",
    "text": "plain text",
    "txt": "plain text",
    "py": "python",
    "sh": "shell",
    "zsh": "shell",
    "bash": "bash",
    "ts": "typescript",
    "tsx": "typescript",
    "js": "javascript",
    "jsx": "javascript",
    "yml": "yaml",
    "rs": "rust",
    "md": "markdown",
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
            with _opener.open(req, timeout=30) as resp:
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


def upload_image_file(token: str, file_path: Path) -> str:
    """Upload a local image to Notion via the File Upload API. Returns the file_upload id.

    两步:① POST /file_uploads 建 upload object 拿 upload_url;② multipart POST 文件到 upload_url。
    成功后该 id 可直接用于 image block 的 {"type":"file_upload","file_upload":{"id":...}}。
    """
    import uuid
    up = notion_request("POST", "file_uploads", token, {})
    uid = up["id"]
    upload_url = up["upload_url"]

    data = file_path.read_bytes()
    mime, _ = mimetypes.guess_type(str(file_path))
    mime = mime or "image/png"
    boundary = "----notion" + uuid.uuid4().hex
    body = b""
    body += f"--{boundary}\r\n".encode()
    body += (
        f'Content-Disposition: form-data; name="file"; '
        f'filename="{file_path.name}"\r\n'
    ).encode()
    body += f"Content-Type: {mime}\r\n\r\n".encode()
    body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(upload_url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

    last_error: Exception | None = None
    for attempt in range(5):
        try:
            with _opener.open(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result.get("status") != "uploaded":
                    raise RuntimeError(f"Upload status != uploaded: {result.get('status')}")
                return uid
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code in (429, 500, 502, 503, 504) and attempt < 4:
                last_error = exc
                time.sleep(2.0 * (attempt + 1))
                continue
            raise RuntimeError(f"Image upload failed: HTTP {exc.code} {detail}") from exc
        except (urllib.error.URLError, ssl.SSLError, EOFError, ConnectionError, OSError) as exc:
            last_error = exc
            if attempt == 4:
                break
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(last_error or "Image upload failed with unknown network error")


def resolve_local_images(blocks: list[dict[str, Any]], token: str, base_dir: Path) -> None:
    """In-place: 把 markdown_to_blocks 产出的 _local_image 占位块上传并替换成真 image block。"""
    for blk in blocks:
        if blk.get("type") != "_local_image":
            continue
        rel = blk["_local_image"]["path"]
        caption = blk["_local_image"].get("caption", "")
        img_path = (base_dir / rel).resolve()
        if not img_path.exists():
            raise RuntimeError(f"图片不存在: {img_path} (markdown 里写的是 {rel})")
        uid = upload_image_file(token, img_path)
        blk.clear()
        image_obj: dict[str, Any] = {"type": "file_upload", "file_upload": {"id": uid}}
        if caption:
            image_obj["caption"] = [{"type": "text", "text": {"content": caption[:2000]}}]
        blk["object"] = "block"
        blk["type"] = "image"
        blk["image"] = image_obj


def load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {
        "parent_page_id": DEFAULT_PARENT_PAGE_ID,
        "database_id": None,
        "database_title": "量化系统底层修炼｜OS & C++",
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
            # database — that scatters notes across orphan DBs. Re-raise instead.
            msg = str(exc)
            if "HTTP 404" not in msg:
                raise
            config["database_id"] = None

    title = config.get("database_title") or "量化系统底层修炼｜OS & C++"
    parent_page_id = config.get("parent_page_id") or DEFAULT_PARENT_PAGE_ID
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": {
            "Name": {"title": {}},
            "Topic": {"rich_text": {}},
            "Part": {"select": {}},
            "Stage": {"select": {}},
            "Tags": {"multi_select": {}},
            "Difficulty": {"select": {}},
            "Tier": {"select": {}},
            "Lesson Date": {"date": {}},
            "Status": {"select": {}},
            "Source": {"rich_text": {}},
            "Discord Message": {"url": {}},
        },
    }
    database = notion_request("POST", "databases", token, payload)
    config["database_id"] = database["id"]
    save_config(config)
    return database


def ensure_self_relation(token: str, database_id: str) -> None:
    """确保 DB 上有 sub-item 所需的自关联字段（Parent item ↔ 同步反向字段）。

    Notion 的「缩进树 / Sub-item」底层就是一个 dual_property 自关联。
    幂等：已存在指向本库的 relation 字段则跳过，不重复加。
    """
    meta = notion_request("GET", f"databases/{database_id}", token)
    for prop in meta.get("properties", {}).values():
        if prop.get("type") == "relation":
            rel = prop.get("relation", {})
            if rel.get("database_id", "").replace("-", "") == database_id.replace("-", ""):
                return  # 已有自关联，复用
    notion_request("PATCH", f"databases/{database_id}", token, {
        "properties": {
            "Parent item": {"relation": {"database_id": database_id, "type": "dual_property", "dual_property": {}}}
        }
    })


def ensure_parent_page(token: str, database_id: str, parent_title: str) -> str:
    """查找或创建一个充当「总纲根」的页面，返回其 page_id（幂等，按 Name 精确匹配）。"""
    res = notion_request("POST", f"databases/{database_id}/query", token, {
        "filter": {"property": "Name", "title": {"equals": parent_title}}, "page_size": 1,
    })
    if res.get("results"):
        return res["results"][0]["id"]
    page = notion_request("POST", "pages", token, {
        "parent": {"database_id": database_id},
        "properties": {
            "Name": {"title": [{"type": "text", "text": {"content": parent_title}}]},
            "Status": {"select": {"name": "Published"}},
            "Source": {"rich_text": [{"type": "text", "text": {"content": "quant-curriculum"}}]},
        },
    })
    return page["id"]


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


def _is_table_row(s: str) -> bool:
    s = s.strip()
    return s.startswith("|") and s.count("|") >= 2


def _is_table_sep(s: str) -> bool:
    s = s.strip()
    return bool(re.match(r"^\|[\s:|-]+\|$", s)) and "-" in s


def _parse_cells(s: str) -> list[str]:
    s = s.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def table_block(rows: list[list[str]], has_header: bool) -> dict[str, Any]:
    width = max((len(r) for r in rows), default=1)
    children: list[dict[str, Any]] = []
    for r in rows:
        cells = []
        for i in range(width):
            cell_text = r[i] if i < len(r) else ""
            # rich_text 不解析 **bold**，去掉标记避免单元格里残留星号
            cell_text = cell_text.replace("**", "")
            cells.append(rich_text(cell_text))
        children.append({"type": "table_row", "table_row": {"cells": cells}})
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": has_header,
            "has_row_header": False,
            "children": children,
        },
    }


def markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    in_code = False
    code_lang = "plain text"
    code_lines: list[str] = []
    para_lines: list[str] = []

    table_rows: list[list[str]] = []
    table_has_header = False

    def flush_table() -> None:
        nonlocal table_has_header
        if table_rows:
            blocks.append(table_block(list(table_rows), table_has_header))
            table_rows.clear()
            table_has_header = False

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

        # Table detection: collect consecutive | ... | rows
        if _is_table_row(line):
            if _is_table_sep(line):
                # separator row marks header above
                if table_rows:
                    table_has_header = True
                continue
            flush_para()
            table_rows.append(_parse_cells(line))
            continue
        else:
            flush_table()

        if not line.strip():
            flush_para()
            continue

        heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading_match:
            flush_para()
            blocks.append(heading(len(heading_match.group(1)), heading_match.group(2).strip()))
            continue

        # Standalone local image: ![caption](relative/path.png)
        img_match = re.match(r"^!\[(.*?)\]\(([^)]+)\)\s*$", line.strip())
        if img_match:
            flush_para()
            blocks.append({
                "type": "_local_image",
                "_local_image": {
                    "caption": img_match.group(1).strip(),
                    "path": img_match.group(2).strip(),
                },
            })
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
    flush_table()
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
    # 上传本地图片 -> 转 image block（base_dir = markdown 所在目录，相对路径据此解析）
    resolve_local_images(blocks, token, Path(args.file).resolve().parent)

    archived = 0
    if not getattr(args, "no_upsert", False):
        archived = archive_existing_pages(token, database["id"], args.title)

    properties: dict[str, Any] = {
        "Name": {"title": [{"type": "text", "text": {"content": args.title}}]},
        "Topic": {"rich_text": [{"type": "text", "text": {"content": args.topic or args.title}}]},
        "Status": {"select": {"name": args.status}},
        "Source": {"rich_text": [{"type": "text", "text": {"content": "quant-curriculum"}}]},
    }
    if args.part:
        properties["Part"] = {"select": {"name": args.part[:100]}}
    if args.stage:
        properties["Stage"] = {"select": {"name": args.stage[:100]}}
    if args.tags:
        tag_names = [t.strip()[:100] for t in args.tags.split(",") if t.strip()]
        properties["Tags"] = {"multi_select": [{"name": t} for t in tag_names]}
    if args.lesson_date:
        properties["Lesson Date"] = {"date": {"start": args.lesson_date}}
    if args.difficulty:
        properties["Difficulty"] = {"select": {"name": args.difficulty[:100]}}
    if args.tier:
        properties["Tier"] = {"select": {"name": args.tier[:100]}}

    page = notion_request(
        "POST",
        "pages",
        token,
        {"parent": {"database_id": database["id"]}, "properties": properties},
    )
    for batch in chunks(blocks):
        notion_request("PATCH", f"blocks/{page['id']}/children", token, {"children": batch})

    parent_page_id = None
    parent_title = getattr(args, "parent_title", "")
    if parent_title:
        ensure_self_relation(token, database["id"])
        parent_page_id = ensure_parent_page(token, database["id"], parent_title)
        notion_request("PATCH", f"pages/{page['id']}", token, {
            "properties": {"Parent item": {"relation": [{"id": parent_page_id}]}}
        })

    result = {
        "page_id": page["id"],
        "url": page.get("url") or page_url(page["id"]),
        "database_id": database["id"],
        "database_title": config.get("database_title"),
        "blocks": len(blocks),
        "archived_old": archived,
        "parent_page_id": parent_page_id,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ensure-db", action="store_true", help="Create or verify the dedicated Notion database.")
    parser.add_argument("--file", help="Markdown lesson file to sync.")
    parser.add_argument("--title", help="Lesson title.")
    parser.add_argument("--topic", default="")
    parser.add_argument("--part", default="", help="部分: C++ / OS / 综合")
    parser.add_argument("--stage", default="", help="阶段, e.g. C4·内存模型与并发 / O4·中断与内核旁路")
    parser.add_argument("--tags", default="", help="Comma-separated multi-select tags.")
    parser.add_argument("--difficulty", default="", help="🟢入门 / 🟡进阶 / 🔴硬核 / ⚫天花板")
    parser.add_argument("--tier", default="", help="C·研究员 / B·HPC平台 / A·低延迟核心")
    parser.add_argument("--lesson-date", default="")
    parser.add_argument("--parent-title", default="",
                        help="挂到某个总纲根页下形成 Sub-item 缩进树（按 Name 幂等找/建该父页）。")
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
