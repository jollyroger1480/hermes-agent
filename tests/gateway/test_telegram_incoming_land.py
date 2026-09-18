"""Telegram incoming-folder lander: execute mkdir/copy, do not narrate."""
from pathlib import Path

from gateway.telegram_incoming_land import (
    apply_inbound_file_ops,
    land_file_ops,
    parse_file_op_intent,
)


def test_parse_mkdir_incoming_typo():
    intent = parse_file_op_intent("Make a folder in not listed saying incoming.")
    assert intent["wants_mkdir"] is True
    assert intent["file_op_only"] is True


def test_parse_add_photos_typo_ljsted():
    intent = parse_file_op_intent(
        "Add these to incoming folder under not ljsted."
    )
    assert intent["wants_mkdir"] is True
    assert intent["wants_copy"] is True
    assert intent["file_op_only"] is True


def test_parse_nos_draft_is_not_file_op_only():
    intent = parse_file_op_intent("/nos 4.99 draft this gasket")
    assert intent["file_op_only"] is False
    assert intent["wants_mkdir"] is False


def test_parse_queue_is_not_file_op_only():
    intent = parse_file_op_intent("/queue")
    assert intent["file_op_only"] is False


def test_land_mkdir_and_copy(tmp_path, monkeypatch):
    incoming = tmp_path / "not-listed" / "incoming"
    monkeypatch.setattr(
        "gateway.telegram_incoming_land.INCOMING", incoming
    )
    monkeypatch.setattr(
        "gateway.telegram_incoming_land.NOT_LISTED", tmp_path / "not-listed"
    )
    src = tmp_path / "img_abc.jpg"
    src.write_bytes(b"jpeg-bytes")
    result = land_file_ops(
        "Add these to incoming folder under not listed.",
        [str(src)],
    )
    assert result.did is True
    assert (incoming / "img_abc.jpg").read_bytes() == b"jpeg-bytes"
    assert "DONE on disk" in result.report
    # idempotent
    again = land_file_ops(
        "Add these to incoming folder under not listed.",
        [str(src)],
    )
    assert again.copied == []
    assert (incoming / "img_abc.jpg").is_file()


def test_apply_appends_proof(tmp_path, monkeypatch):
    incoming = tmp_path / "incoming"
    monkeypatch.setattr(
        "gateway.telegram_incoming_land.INCOMING", incoming
    )
    monkeypatch.setattr(
        "gateway.telegram_incoming_land.NOT_LISTED", tmp_path
    )
    out = apply_inbound_file_ops(
        "Make a folder in not listed saying incoming.", []
    )
    assert "GATEWAY_FILE_OP_DONE" in out
    assert incoming.is_dir()
