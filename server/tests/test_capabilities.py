from __future__ import annotations

import pytest

from actions import available_action_names, reply_schema
from capabilities import (
    ASSUMED_CAPABILITIES,
    ProtocolMismatch,
    negotiate_protocol,
    parse_capabilities,
    unknown_hardware,
)


def _manifest(**overrides) -> dict:
    message = {
        "v": "eva/1",
        "type": "capabilities",
        "robot": {"id": "pi-01", "name": "Eva"},
        "sensors": ["microphone"],
        "actuators": ["base", "speaker", "eyes"],
    }
    message.update(overrides)
    return message


def test_manifest_becomes_an_action_set() -> None:
    capabilities = parse_capabilities(_manifest())
    assert capabilities is not None
    assert capabilities.robot_id == "pi-01"
    assert available_action_names(capabilities) == {"speak", "move_base"}


def test_missing_hardware_removes_the_action() -> None:
    """The point of the whole handshake: no base, no move_base."""
    capabilities = parse_capabilities(_manifest(actuators=["speaker", "eyes"]))
    assert capabilities is not None
    assert available_action_names(capabilities) == {"speak"}


def test_the_model_cannot_name_an_action_the_robot_lacks() -> None:
    """
    Enforced in the grammar, not the prompt.

    A robot with a base gets `move_base` in the schema's enum; one without gets
    no schema at all, because there is nothing left for the model to call.
    """
    with_base = parse_capabilities(_manifest())
    without_base = parse_capabilities(_manifest(actuators=["speaker"]))
    assert with_base is not None and without_base is not None

    schema = reply_schema(with_base)
    assert schema is not None
    assert schema["properties"]["commands"]["items"]["properties"]["name"]["enum"] == ["move_base"]
    # say before commands, so speech streams before the model decides to move
    assert list(schema["properties"]) == ["say", "commands"]

    assert reply_schema(without_base) is None


def test_speak_is_never_offered_to_the_model() -> None:
    """It writes speech into `say`; a speak command would be a second way to talk."""
    capabilities = parse_capabilities(_manifest())
    assert capabilities is not None
    schema = reply_schema(capabilities)
    assert schema is not None
    assert "speak" not in schema["properties"]["commands"]["items"]["properties"]["name"]["enum"]


def test_an_empty_declaration_is_refused() -> None:
    """Far likelier a bug on the robot than a robot with no hardware."""
    assert parse_capabilities(_manifest(sensors=[], actuators=[])) is None


def test_unknown_hardware_is_reported_not_rejected() -> None:
    capabilities = parse_capabilities(_manifest(sensors=["microphone", "lidar"]))
    assert capabilities is not None
    assert capabilities.has_sensor("lidar")
    assert unknown_hardware(capabilities) == ["lidar"]


def test_an_undeclared_robot_keeps_everything() -> None:
    """Firmware older than the handshake must not silently lose its wheels."""
    assert available_action_names(ASSUMED_CAPABILITIES) == {"speak", "move_base"}
    assert ASSUMED_CAPABILITIES.declared is False


class TestProtocolNegotiation:
    def test_a_shared_version_is_chosen(self) -> None:
        assert negotiate_protocol({"protocol": ["eva/1"]}, default="eva/1") == "eva/1"

    def test_a_bare_string_is_accepted(self) -> None:
        assert negotiate_protocol({"protocol": "eva/1"}, default="eva/1") == "eva/1"

    def test_silence_means_the_version_it_was_written_against(self) -> None:
        assert negotiate_protocol({}, default="eva/1") == "eva/1"

    def test_no_shared_version_is_a_hard_failure(self) -> None:
        with pytest.raises(ProtocolMismatch):
            negotiate_protocol({"protocol": ["eva/9"]}, default="eva/1")
