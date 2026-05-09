from action_rules import match_action_from_text, normalize_text


def test_normalize_text_basic() -> None:
    assert normalize_text("Turn LEFT!!") == "turn left"
    assert normalize_text("go ahead") == "go forward"


def test_match_action_turn_left() -> None:
    out = match_action_from_text("Turn left")
    assert out is not None
    assert out["key"] == "turn_left"
