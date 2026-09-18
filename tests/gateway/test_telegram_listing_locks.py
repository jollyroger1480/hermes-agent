"""Telegram listing lock: ship pair is never BIN; /nos does not price."""
from gateway.telegram_listing_locks import (
    apply_inbound_listing_locks,
    is_active_listing_draft,
    parse_listing_lock,
)


def test_slash_pair_with_ship_word():
    lock = parse_listing_lock("these 4.99 / 9.99 ship like yesterday")
    assert lock.ground == "4.99"
    assert lock.priority == "9.99"
    assert lock.bin_price is None


def test_slash_pair_without_ship_word_if_tiers():
    lock = parse_listing_lock("/nos 4.99 / 9.99")
    assert lock.ground == "4.99"
    assert lock.priority == "9.99"
    assert lock.bin_price is None
    assert lock.nos_trailing_was_ship is False


def test_ground_priority_words_in_between():
    lock = parse_listing_lock("3.99 ground / 9.99 priority on all 3")
    assert lock.ground == "3.99"
    assert lock.priority == "9.99"


def test_ship_cmd_two_amounts():
    lock = parse_listing_lock("/ship 4.99 9.99")
    assert lock.ground == "4.99"
    assert lock.priority == "9.99"


def test_ship_paid_one_amount_499_defaults_pri_999():
    lock = parse_listing_lock("/ship-paid 4.99")
    assert lock.ground == "4.99"
    assert lock.priority == "9.99"


def test_nos_trailing_number_is_shipping_not_bin():
    lock = parse_listing_lock("/nos 4.99 draft this gasket")
    assert lock.bin_price is None
    assert lock.ground == "4.99"
    assert lock.priority == "9.99"
    assert lock.nos_trailing_was_ship is True
    out = apply_inbound_listing_locks("/nos 4.99 draft this gasket")
    assert "/nos 4.99" not in out
    assert out.startswith("/nos draft this gasket")
    assert "SHIPPING: USPS Ground Advantage $4.99" in out
    assert "BIN_LOCK" not in out


def test_nos_does_not_take_non_ship_trailing_as_bin():
    lock = parse_listing_lock("/nos 16.99 draft this gasket")
    assert lock.bin_price is None
    assert lock.ground is None
    out = apply_inbound_listing_locks("/nos 16.99 draft this gasket")
    assert "BIN_LOCK" not in out
    assert "LISTING_LOCK" not in out


def test_explicit_bin_wins():
    lock = parse_listing_lock("/nos bin 16.99  4.99 / 9.99 ship")
    assert lock.ground == "4.99"
    assert lock.priority == "9.99"
    assert lock.bin_price == "16.99"


def test_nos_trailing_ship_plus_bin_keyword():
    lock = parse_listing_lock("/nos 4.99 bin 16.99")
    assert lock.ground == "4.99"
    assert lock.priority == "9.99"
    assert lock.bin_price == "16.99"
    out = apply_inbound_listing_locks("/nos 4.99 bin 16.99")
    assert "/nos 4.99" not in out
    assert "BIN_LOCK: $16.99" in out
    assert "Ground Advantage $4.99" in out


def test_leave_dollar_is_bin():
    lock = parse_listing_lock("leave $18.99 on the pinion")
    assert lock.bin_price == "18.99"
    assert lock.ground is None


def test_bin_range_not_ship():
    lock = parse_listing_lock("comps look like 16.99 / 19.99")
    assert lock.ground is None
    assert lock.bin_price is None


def test_apply_injects_and_is_idempotent():
    msg = "/nos 4.99 / 9.99 ship"
    out = apply_inbound_listing_locks(msg)
    assert "LISTING_LOCK" in out
    assert "PRICE: 4.99" in out
    assert "Those dollars are SHIPPING" in out
    assert "BIN from comps" in out
    again = apply_inbound_listing_locks(out)
    assert again.count("[LISTING_LOCK") == 1


def test_bare_nos_does_not_inject_price_hunt():
    assert apply_inbound_listing_locks("/nos draft this gasket") == "/nos draft this gasket"


def test_queue_nos_is_active_listing_draft():
    assert is_active_listing_draft("/queue /nos 4.99 / 9.99 priority")
    assert is_active_listing_draft("/queue")
    assert is_active_listing_draft("/q")
    assert is_active_listing_draft("/nos")
    assert not is_active_listing_draft("what is this")


def test_queue_with_photos_injects_photo_gate(monkeypatch):
    monkeypatch.setattr(
        "gateway.telegram_listing_locks.scan_photo_pns",
        lambda paths, timeout=90: "SCAN_PN found=['S205']\nSCAN_PN not_listed_match=[]",
    )
    out = apply_inbound_listing_locks(
        "/queue",
        ["/data/userhome/.hermes/cache/images/img_aaa.jpg"],
    )
    assert "LISTING_PHOTO_GATE" in out
    assert "N_PHOTOS=1" in out


def test_nos_with_photos_injects_photo_gate(monkeypatch):
    monkeypatch.setattr(
        "gateway.telegram_listing_locks.scan_photo_pns",
        lambda paths, timeout=90: "SCAN_PN found=['S205']\nSCAN_PN not_listed_match=[]",
    )
    out = apply_inbound_listing_locks(
        "/nos",
        ["/data/userhome/.hermes/cache/images/img_aaa.jpg"],
    )
    assert "LISTING_PHOTO_GATE" in out
    assert "N_PHOTOS=1" in out
    assert "img_aaa.jpg" in out
    assert "Seller Notes" in out
    assert "positional slug then paths" in out
    assert "SCAN_PN found=['S205']" in out
    assert "vision_tools" in out
    assert "FORBIDDEN" in out
    again = apply_inbound_listing_locks(out, ["/data/userhome/.hermes/cache/images/img_aaa.jpg"])
    assert again.count("[LISTING_PHOTO_GATE") == 1


def test_photos_without_draft_ask_do_not_inject_photo_gate():
    out = apply_inbound_listing_locks(
        "what is this",
        ["/data/userhome/.hermes/cache/images/img_aaa.jpg"],
    )
    assert "LISTING_PHOTO_GATE" not in out
