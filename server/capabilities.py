"""
capabilities.py — What the robot on the other end of this session can do.

The robot announces its hardware on connect and the server answers with the
subset of the action registry that hardware supports. Everything downstream
reads the answer from here: which actions are legal for this session, and which
of them the language model is even allowed to name.

This is what makes hardware pluggable. A robot without a base is never sent
`move_base` — not because the prompt asked nicely, but because the name is
absent from the model's output grammar and rejected by validation behind it.

The handshake follows the shape every capability-negotiating protocol converges
on: each side declares what it will accept, the server acknowledges what it
took, and a version it cannot speak is a hard failure rather than a limp.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional

# Hardware this server knows how to use. A manifest may name more — unknown
# entries are kept and reported back rather than rejected, so a robot can grow
# a sensor before the server has anything to do with it.
KNOWN_ACTUATORS = ("base", "speaker", "eyes")
KNOWN_SENSORS = ("microphone", "camera")


@dataclass(frozen=True)
class RobotCapabilities:
    """One robot's declared hardware."""

    robot_id: str = "unknown"
    name: str = "robot"
    sensors: FrozenSet[str] = frozenset()
    actuators: FrozenSet[str] = frozenset()
    # False when the robot never sent a manifest. Explicit because the fallback
    # below is deliberately permissive, and "assumed" should be greppable in a
    # log rather than indistinguishable from a real declaration.
    declared: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

    def has_actuator(self, name: str) -> bool:
        return name in self.actuators

    def has_sensor(self, name: str) -> bool:
        return name in self.sensors

    def describe(self) -> str:
        sensors = ", ".join(sorted(self.sensors)) or "none"
        actuators = ", ".join(sorted(self.actuators)) or "none"
        return f"{self.name} [{self.robot_id}] sensors: {sensors}; actuators: {actuators}"


# A robot that connects without announcing anything is assumed to have
# everything. Firmware older than the handshake predates this file, and
# silently taking movement away from it would be a worse failure than trusting
# it — validate_command() still gates every command either way.
ASSUMED_CAPABILITIES = RobotCapabilities(
    robot_id="undeclared",
    name="undeclared robot",
    sensors=frozenset(KNOWN_SENSORS),
    actuators=frozenset(KNOWN_ACTUATORS),
    declared=False,
)


class ProtocolMismatch(Exception):
    """The robot cannot speak any protocol version this server supports."""

    def __init__(self, offered: List[str]) -> None:
        self.offered = offered
        super().__init__(f"robot speaks {offered or ['nothing']}, server speaks {list(SUPPORTED_PROTOCOLS)}")


# Every protocol version this server can still serve, newest first. A second
# entry appears here the first time a change breaks an older robot — until
# then, saying so honestly is more useful than pretending to negotiate.
SUPPORTED_PROTOCOLS = ("eva/1",)


def negotiate_protocol(message: Dict[str, Any], *, default: str) -> str:
    """
    Pick the protocol version for this session.

    The robot may offer a list (`protocol`), a single string, or nothing at all.
    Nothing at all means firmware from before the handshake, which by definition
    speaks the version it was written against — so it gets the default rather
    than an error it has no code to read.
    """
    offered = message.get("protocol")
    if offered is None:
        return default
    if isinstance(offered, str):
        offered = [offered]
    if not isinstance(offered, list):
        raise ProtocolMismatch([])

    candidates = [v for v in offered if isinstance(v, str)]
    for version in SUPPORTED_PROTOCOLS:
        if version in candidates:
            return version
    raise ProtocolMismatch(candidates)


def _string_set(value: Any) -> FrozenSet[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(item.strip() for item in value if isinstance(item, str) and item.strip())


_ENVELOPE_KEYS = {"v", "type", "ts_ms", "id", "session_id", "protocol", "robot", "sensors", "actuators"}


def parse_capabilities(message: Dict[str, Any]) -> Optional[RobotCapabilities]:
    """
    Read a `capabilities` message into a manifest.

    Returns None when the message declares neither sensors nor actuators. An
    empty declaration is far likelier to be a bug on the robot than a robot with
    no hardware, and honouring it would leave Eva mute and still for a reason
    nobody could see from the outside.
    """
    robot = message.get("robot")
    robot = robot if isinstance(robot, dict) else {}

    sensors = _string_set(message.get("sensors"))
    actuators = _string_set(message.get("actuators"))
    if not sensors and not actuators:
        return None

    robot_id = robot.get("id")
    name = robot.get("name")

    return RobotCapabilities(
        robot_id=robot_id.strip() if isinstance(robot_id, str) and robot_id.strip() else "unknown",
        name=name.strip() if isinstance(name, str) and name.strip() else "robot",
        sensors=sensors,
        actuators=actuators,
        declared=True,
        extra={k: v for k, v in message.items() if k not in _ENVELOPE_KEYS},
    )


def unknown_hardware(capabilities: RobotCapabilities) -> List[str]:
    """Declared hardware this server has no use for. Reported back, never rejected."""
    unknown = [s for s in sorted(capabilities.sensors) if s not in KNOWN_SENSORS]
    unknown += [a for a in sorted(capabilities.actuators) if a not in KNOWN_ACTUATORS]
    return unknown
