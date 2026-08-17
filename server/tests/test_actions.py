from actions import MOVE_COMMANDS, list_actions, validate_command
from capabilities import RobotCapabilities
from planner import plan_from_transcript


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


def test_validation_rejects_an_action_this_robot_cannot_perform() -> None:
    command = {"name": "move_base", "args": {"command": "forward"}}
    assert validate_command(command, {"speak", "move_base"}) is not None
    assert validate_command(command, {"speak"}) is None


def test_a_rule_is_all_or_nothing_against_the_hardware() -> None:
    """
    "Moving forward." and then not moving is the failure worth preventing.

    Half a rule is worse than none of it: the confirmation is a promise, so a
    robot that cannot keep it must not make it. The utterance goes to the
    language model instead, which can say something true.
    """
    full = plan_from_transcript("go forward", allowed={"speak", "move_base"})
    assert [c["name"] for c in full.commands] == ["speak", "move_base"]
    assert full.language_model_input_text is None

    voice_only = plan_from_transcript("go forward", allowed={"speak"})
    assert voice_only.commands == []
    assert voice_only.language_model_input_text == "go forward"


def test_the_registry_records_what_hardware_each_action_needs() -> None:
    requires = {a["name"]: a["requires"] for a in list_actions()}
    assert requires == {"speak": ["speaker"], "move_base": ["base"]}


def test_capabilities_and_the_registry_agree_on_one_robot() -> None:
    """GET /v1/actions lists everything; a session only ever offers a subset."""
    from actions import available_action_names

    wheeled = RobotCapabilities(actuators=frozenset({"base", "speaker"}), declared=True)
    assert available_action_names(wheeled) == {a["name"] for a in list_actions()}
