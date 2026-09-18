"""Parse Telegram listing dollars before the model can mix ship vs BIN.

Born 2026-08-23: Julian said ``4.99 / 9.99 ship`` (and ``/nos 4.99``).
Kimi wrote ``PRICE: 4.99`` and ``SHIPPING: … $9.99`` Ground. Prompt-only
"stated BIN wins" made that worse. This lock is injected into the inbound
text so Kimi/Composer never see a bare ``/nos 4.99`` as a price.

``/nos`` never sets BIN. A trailing dollar on ``/nos`` is Ground shipping.
BIN only from bin/price/leave.

2026-08-29: /nos + photos was answering chat-only (0 tools). When this
message has images and is an active draft (/nos /used /listing /draft),
also inject LISTING_PHOTO_GATE so intake + 1-listing.txt is mandatory.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_MONEY = r"(?:\$\s*)?(\d+\.\d{2})"
_PAIR_RE = re.compile(
    rf"{_MONEY}\s*(?:ground|ga|usps)?\s*/\s*{_MONEY}",
    re.I,
)
_SHIP_CMD_RE = re.compile(
    rf"(?:/ship-paid|/ship|ship-paid)\s+{_MONEY}(?:\s+{_MONEY})?",
    re.I,
)
_SHIP_WORD_RE = re.compile(
    r"\b(?:ship(?:ping|ped)?|ground|priority|usps|/ship-paid|/ship)\b",
    re.I,
)
_BIN_RE = re.compile(
    rf"(?:^|\s)(?:/bin|bin|price|leave)\s*:?\s*{_MONEY}\b",
    re.I,
)
_NOS_TRAILING_RE = re.compile(rf"/nos\s+{_MONEY}(?!\s*/)", re.I)
_LOCK_MARK = "[LISTING_LOCK"
_PHOTO_GATE_MARK = "[LISTING_PHOTO_GATE"
_ACTIVE_DRAFT_RE = re.compile(
    r"(?:^|\s)/(?:nos|used|tested|open[_-]?box|random[_-]?lot|pn[_-]?draft|"
    r"end[_-]?new|listing|ship-paid|queue|q)\b"
    r"|\b(?:draft(?:ing)?|make a listing|create the listing|put it in)\b",
    re.I,
)
_INTAKE_PY = Path("/home/jollyroge1480/ebay/scripts/listing_photo_intake.py")
_RAPIDOCR_PY = Path("/home/jollyroge1480/ebay/.venv-rapidocr/bin/python")

# Typical buyer-paid Ground / Priority figures. A slash pair of these is
# shipping even if Julian omitted the word "ship".
_GROUND_TIERS = frozenset({"3.99", "4.99", "5.99", "6.99", "7.99", "8.99", "9.99"})
_PRI_TIERS = frozenset({"9.99", "12.99", "14.99"})


def _norm(raw: str | None) -> str | None:
    if raw is None:
        return None
    try:
        val = float(raw)
    except ValueError:
        return None
    return f"{val:.2f}"


@dataclass
class ListingLock:
    ground: str | None = None
    priority: str | None = None
    bin_price: str | None = None
    nos_trailing_was_ship: bool = False

    @property
    def hit(self) -> bool:
        return bool(self.ground or self.priority or self.bin_price)


def parse_listing_lock(text: str) -> ListingLock:
    blob = text or ""
    lock = ListingLock()
    ship_word = bool(_SHIP_WORD_RE.search(blob))

    pair = _PAIR_RE.search(blob)
    if pair:
        g, p = _norm(pair.group(1)), _norm(pair.group(2))
        if g and p and (ship_word or (g in _GROUND_TIERS and p in _PRI_TIERS)):
            lock.ground, lock.priority = g, p

    if lock.ground is None:
        cmd = _SHIP_CMD_RE.search(blob)
        if cmd:
            g, p = _norm(cmd.group(1)), _norm(cmd.group(2))
            lock.ground = g
            if p:
                lock.priority = p
            elif g == "4.99":
                lock.priority = "9.99"
            else:
                lock.priority = "14.99"

    bin_m = _BIN_RE.search(blob)
    if bin_m:
        b = _norm(bin_m.group(1))
        if b and b not in {lock.ground, lock.priority}:
            lock.bin_price = b

    # /nos never looks for BIN. Trailing $ after /nos (no slash pair) is
    # Ground shipping when it is a Ground tier — same as /ship-paid 4.99.
    nos = _NOS_TRAILING_RE.search(blob)
    if nos:
        n = _norm(nos.group(1))
        if n and n != lock.bin_price and n in _GROUND_TIERS and lock.ground is None:
            lock.ground = n
            lock.nos_trailing_was_ship = True
            if lock.priority is None:
                lock.priority = "9.99" if n == "4.99" else "14.99"

    return lock


def format_listing_lock(lock: ListingLock) -> str:
    if not lock.hit:
        return ""
    lines = [
        "[LISTING_LOCK — machine parse. Obey this over any dollar in the user text.]",
    ]
    if lock.ground and lock.priority:
        lines.append(
            f"SHIPPING: USPS Ground Advantage ${lock.ground}. "
            f"Priority Mail upgrade ${lock.priority}."
        )
        lines.append(
            f"Do NOT write PRICE: {lock.ground} or PRICE: {lock.priority} "
            "from this message. Those dollars are SHIPPING."
        )
    if lock.bin_price:
        lines.append(f"BIN_LOCK: ${lock.bin_price}")
    else:
        lines.append(
            "BIN from comps (Browse + leftover floor). "
            "/nos does not take a BIN — do not hunt a price on /nos."
        )
    lines.append("[/LISTING_LOCK]")
    return "\n".join(lines)


def is_active_listing_draft(text: str) -> bool:
    """True when this inbound is a listing draft, not chat-only ID."""
    return bool(_ACTIVE_DRAFT_RE.search(text or ""))


def scan_photo_pns(image_paths: list[str], timeout: int = 90) -> str:
    """Run listing_photo_intake --scan-pn with the RapidOCR venv.

    System python's cv2 often prints ``OpenCV bindings requires numpy``
    because RapidOCR's site-packages are not on that interpreter. The
    isolated venv has numpy+cv2 together (2026-08-29 Telegram 30/30).
    """
    paths = [p for p in image_paths if p]
    if not paths or not _INTAKE_PY.is_file():
        return ""
    py = str(_RAPIDOCR_PY) if _RAPIDOCR_PY.is_file() else sys.executable
    try:
        proc = subprocess.run(
            [py, str(_INTAKE_PY), "--scan-pn", *paths],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return f"SCAN_PN error={exc}"
    blob = f"{proc.stdout or ''}{proc.stderr or ''}"
    keep = [
        ln
        for ln in blob.splitlines()
        if ln.startswith("SCAN_PN") or ln.startswith("PN_")
    ]
    return "\n".join(keep) if keep else (blob.strip()[:400] or "SCAN_PN found=[]")


def format_photo_gate(
    n_images: int,
    image_paths: list[str] | None,
    scan_block: str = "",
) -> str:
    listed = "\n".join(f"- {p}" for p in (image_paths or []) if p)
    album_dirs = []
    for p in image_paths or []:
        if not p:
            continue
        parent = str(Path(p).parent)
        if "/albums/" in parent.replace("\\", "/") and parent not in album_dirs:
            album_dirs.append(parent)
    album_line = ""
    if album_dirs:
        album_line = "ALBUM_DIR=" + " ".join(album_dirs) + "\n"
        album_line += (
            "Same-album extra shots live in ALBUM_DIR — intake that folder, "
            "do not ls the whole cache/images pile.\n"
        )
    ocr = (scan_block or "").strip() or "SCAN_PN found=[] (gateway OCR empty)"
    return (
        "[LISTING_PHOTO_GATE — ACTIVE DRAFT. Photos on this message. Not chat-only.]\n"
        f"N_PHOTOS={n_images}\n"
        f"{album_line}"
        "This-message image paths (intake THESE only; do not mix albums):\n"
        f"{listed}\n"
        "Vision is primary (vision_analyze: MiniMax / Mistral / Gemini). "
        "vision_tools: vision_analyze is required. "
        "FORBIDDEN: identification-only reply, native-attach to NVIDIA Super, "
        "ITEM SPECIFICS Seller Notes. "
        "RapidOCR --scan-pn is FAILSAFE only:\n"
        f"{ocr}\n"
        "Prefer the lettered box PN from vision prepend / vision_analyze. "
        "If vision is empty or has no lettered PN, use SCAN_PN preferred. "
        "Never leftover-slug from a prior item. Never native-attach pixels "
        "to NVIDIA Super (text-only). vision_analyze on the paths below is "
        "allowed. RapidOCR is not the identity.\n"
        "This turn you MUST:\n"
        "1) python3 /home/jollyroge1480/ebay/scripts/listing_photo_intake.py "
        "<slug-containing-SCAN_PN> <paths above in send order>\n"
        "   Prefer positional slug then paths. If you use --copy, image paths "
        "must follow --copy immediately (never `--copy --slug …`).\n"
        "2) python3 /home/jollyroge1480/ebay/scripts/listing_photo_intake.py "
        "--assert-ready <slug>  (GATE_OK required before draft files)\n"
        "3) write 1-listing.txt with CONDITION NOTES as its own field. "
        "Never ITEM SPECIFICS Seller Notes — that write_file is blocked; "
        "do not retry Seller Notes.\n"
        "Do not reply identification-only. Finish the draft or BLOCKED.\n"
        "[/LISTING_PHOTO_GATE]"
    )


def _stamp_telegram_board(text: str, image_paths: list[str] | None) -> None:
    """Fire-and-forget Telegram ops board. Never block inbound parse."""
    if "pytest" in sys.modules:
        return
    stamp = Path("/home/jollyroge1480/ebay/workflows/telegram-board/stamp.py")
    if not stamp.is_file():
        return
    n = len([p for p in (image_paths or []) if p])
    cmd = [
        sys.executable,
        str(stamp),
        "--phase",
        "inbound",
        "--no-telegram",
        "--ensure-server",
        "--photos",
        str(n),
        "--text",
        (text or "")[:240],
    ]
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


def apply_inbound_listing_locks(
    message_text: str, image_paths: list[str] | None = None
) -> str:
    blob = message_text or ""
    paths = [p for p in (image_paths or []) if p]
    _stamp_telegram_board(blob, paths)
    if _LOCK_MARK not in blob:
        lock = parse_listing_lock(blob)
        if lock.nos_trailing_was_ship:
            # Strip "/nos 4.99" → "/nos" so the model never sees a price token.
            blob = _NOS_TRAILING_RE.sub("/nos", blob, count=1)
        block = format_listing_lock(lock)
        if block:
            blob = (blob.rstrip() + "\n\n" + block).strip()
    if (
        paths
        and _PHOTO_GATE_MARK not in blob
        and is_active_listing_draft(blob)
    ):
        scan = scan_photo_pns(paths)
        blob = (
            blob.rstrip()
            + "\n\n"
            + format_photo_gate(len(paths), paths, scan)
        ).strip()
    return blob
