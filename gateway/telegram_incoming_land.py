"""Deterministic Telegram file ops so the model cannot claim mkdir/copy.

Born 2026-08-23: Kimi on Telegram said it created
``~/ebay/listings/not-listed/incoming/`` and copied 3 box photos. Hermes
logged ``tool_turns=0``; the folder never existed. kimi-cli-proxy returns
text-only ``finish_reason=stop`` and never runs Hermes tools.

This module lands the cheap reversible ops (mkdir under not-listed,
copy attached images into ``incoming/``) from the user text + image
paths. Gateway and the Kimi proxy both call it, then tell the model
what is already on disk.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

NOT_LISTED = Path("/home/jollyroge1480/ebay/listings/not-listed")
INCOMING = NOT_LISTED / "incoming"

_NOT_LISTED_RE = re.compile(r"not[\s_-]*l[ij]sted", re.I)
_INCOMING_RE = re.compile(r"\bincoming\b", re.I)
_MAKE_FOLDER_RE = re.compile(
    r"\b(?:make|create|mkdir|add|put|new)\b.{0,80}\bfolder\b", re.I
)
_COPY_PHOTOS_RE = re.compile(
    r"\b(?:add|put|save|copy|drop|move|stick)\b.{0,80}"
    r"\b(?:these|this|them|photos?|pics?|images?|shots?)\b",
    re.I,
)
_DRAFT_RE = re.compile(
    r"\b(?:/nos|/used|/tested|/queue|/q|draft|listing|preflight|push|title|price)\b",
    re.I,
)
_CLAIM_RE = re.compile(
    r"\b(?:created|copied|saved|added|moved|mkdir|wrote|done|incoming)\b",
    re.I,
)


@dataclass
class FileOpResult:
    did: bool = False
    mkdir: bool = False
    dest: Path | None = None
    copied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    file_op_only: bool = False
    report: str = ""
    prompt_fact: str = ""


def parse_file_op_intent(text: str) -> dict:
    blob = text or ""
    wants_incoming = bool(_INCOMING_RE.search(blob))
    names_not_listed = bool(_NOT_LISTED_RE.search(blob))
    wants_mkdir = bool(_MAKE_FOLDER_RE.search(blob)) and (
        wants_incoming or names_not_listed
    )
    wants_copy = bool(_COPY_PHOTOS_RE.search(blob)) and (
        wants_incoming or names_not_listed
    )
    if wants_incoming and names_not_listed:
        wants_mkdir = True
    if wants_incoming and not wants_mkdir and not wants_copy:
        wants_mkdir = True
    file_op_only = (wants_mkdir or wants_copy) and not _DRAFT_RE.search(blob)
    return {
        "wants_mkdir": wants_mkdir,
        "wants_copy": wants_copy,
        "file_op_only": file_op_only,
        "dest": INCOMING if (wants_mkdir or wants_copy or wants_incoming) else None,
    }


def _copy_one(src: Path, dest_dir: Path) -> tuple[str, bool]:
    """Return (dest name, copied?). Skip same-size existing file."""
    name = src.name
    dest = dest_dir / name
    if dest.exists() and dest.stat().st_size == src.stat().st_size:
        return name, False
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        n = 2
        while dest.exists():
            dest = dest_dir / f"{stem}-{n}{suffix}"
            n += 1
        name = dest.name
    shutil.copy2(src, dest)
    return name, True


def land_file_ops(text: str, image_paths: list[str] | None = None) -> FileOpResult:
    intent = parse_file_op_intent(text)
    result = FileOpResult(file_op_only=bool(intent["file_op_only"]))
    dest: Path | None = intent["dest"]
    if dest is None:
        return result
    dest.mkdir(parents=True, exist_ok=True)
    result.dest = dest
    result.mkdir = True
    result.did = True
    if intent["wants_copy"]:
        for raw in image_paths or []:
            src = Path(str(raw))
            if not src.is_file():
                result.skipped.append(str(raw))
                continue
            name, copied = _copy_one(src, dest)
            if copied:
                result.copied.append(name)
            else:
                result.skipped.append(name)
    names = sorted(p.name for p in dest.iterdir() if p.is_file())
    lines = [
        f"DONE on disk (not a claim): {dest}",
        f"mkdir: yes ({dest})",
    ]
    if intent["wants_copy"]:
        lines.append(f"copied this turn: {len(result.copied)}")
        for n in result.copied:
            lines.append(f"  - {n}")
        if result.skipped:
            lines.append("already present / missing source: " + ", ".join(result.skipped))
    lines.append("ls: " + (", ".join(names) if names else "(empty)"))
    result.report = "\n".join(lines)
    result.prompt_fact = (
        "[GATEWAY_FILE_OP_DONE — these paths exist now. "
        "Report them. Do not invent extra success. Do not mkdir/copy again.]\n"
        + result.report
    )
    return result


def apply_inbound_file_ops(message_text: str, image_paths: list[str] | None) -> str:
    result = land_file_ops(message_text, image_paths)
    if not result.did:
        return message_text
    base = (message_text or "").rstrip()
    return (base + "\n\n" + result.prompt_fact).strip()


def looks_like_success_claim(text: str) -> bool:
    return bool(_CLAIM_RE.search(text or ""))
