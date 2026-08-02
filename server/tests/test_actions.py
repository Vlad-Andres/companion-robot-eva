from actions import MOVE_COMMANDS, list_actions, validate_command


def test_validate_command_normalises_speak() -> None:
    assert validate_command({"name": "speak", "args": {"text": "  hi  "}}) == {
        "name": "speak",
        "args": {"text": "hi"},
    }


def test_validate_command_rejects_bad_input() -> None:
    assert validate_command({"name": "move_base", "args": {"command": "fly"}}) is None
    assert validate_command({"name": "no_such_action", "args": {}}) is None
    assert validate_command({"name": "speak", "args": {"text": "   "}}) is None
    assert validate_command({"name": "speak"}) is None


def test_registry_and_validation_share_one_move_vocabulary() -> None:
    move = next(a for a in list_actions() if a["name"] == "move_base")
    assert move["args_schema"]["properties"]["command"]["enum"] == list(MOVE_COMMANDS)
    for movement in MOVE_COMMANDS:
        assert validate_command({"name": "move_base", "args": {"command": movement}}) is not None
