from app.diff import classify_change


def test_classify_change_new():
    assert classify_change(0, 10) == "NEW"


def test_classify_change_sold():
    assert classify_change(20, 0) == "SOLD"


def test_classify_change_add_trim_unchanged():
    assert classify_change(10, 12) == "ADD"
    assert classify_change(10, 9) == "TRIM"
    assert classify_change(10, 10) == "UNCHANGED"
