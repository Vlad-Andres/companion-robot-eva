from __future__ import annotations

from typing import List

from reply_stream import ReplyStream


def _run(pieces: List[str]) -> tuple[str, object]:
    """Feed the pieces through and collect the speech and the outcome."""
    stream = ReplyStream()
    spoken = "".join(text for piece in pieces for text in stream.add(piece))
    outcome = stream.finish()
    return spoken + outcome.text, outcome


def _characterwise(text: str) -> List[str]:
    return list(text)


REPLY = '{"say": "On my way. Hold tight!", "commands": [{"name": "move_base", "args": {"command": "come_here"}}]}'


def test_speech_and_commands_are_both_recovered() -> None:
    spoken, outcome = _run([REPLY])
    assert spoken == "On my way. Hold tight!"
    assert outcome.commands == [{"name": "move_base", "args": {"command": "come_here"}}]
    assert outcome.structured is True


def test_the_split_between_pieces_does_not_matter() -> None:
    """Token boundaries land wherever the model puts them, including mid-key."""
    spoken, outcome = _run(_characterwise(REPLY))
    assert spoken == "On my way. Hold tight!"
    assert outcome.commands[0]["args"]["command"] == "come_here"


def test_speech_arrives_before_the_object_closes() -> None:
    """
    The reason this module exists.

    Half a reply must already be speakable, or Eva goes quiet for the whole
    generation and says everything at once at the end.
    """
    stream = ReplyStream()
    early = "".join(stream.add('{"say": "On my way. Hold ti'))
    assert early == "On my way. Hold ti"


def test_a_reply_cut_off_mid_object_is_still_spoken() -> None:
    """The token budget running out costs the commands, never the words."""
    spoken, outcome = _run(['{"say": "I can do that, one sec', ""])
    assert spoken == "I can do that, one sec"
    assert outcome.truncated is True
    assert outcome.commands == []


def test_escapes_split_across_pieces_are_not_mangled() -> None:
    spoken, outcome = _run(['{"say": "She said \\', '"hello\\" and \\', 'u00e9 too"}'])
    assert spoken == 'She said "hello" and é too'
    assert outcome.truncated is False


def test_a_plain_text_reply_is_all_speech() -> None:
    """A model ignoring the schema, or a robot with nothing to command."""
    spoken, outcome = _run(["I'm doing ", "well, thank ", "you."])
    assert spoken == "I'm doing well, thank you."
    assert outcome.structured is False
    assert outcome.commands == []


def test_a_one_word_reply_survives() -> None:
    """Too short to ever be identified as JSON, so it is only settled at the end."""
    spoken, _ = _run(["Yes."])
    assert spoken == "Yes."


def test_a_fenced_object_is_unwrapped() -> None:
    """Markdown fences are a model ignoring an instruction, not a different reply."""
    spoken, outcome = _run(['```json\n{"say": "Sure thing.", "commands": []}\n```'])
    assert spoken == "Sure thing."
    assert outcome.commands == []


def test_raw_json_is_never_spoken_aloud() -> None:
    """Whatever else happens, the braces do not reach the synthesiser."""
    spoken, _ = _run([REPLY])
    assert "{" not in spoken and "commands" not in spoken


def test_commands_before_say_still_work() -> None:
    """Property order is a grammar hint, not a guarantee. Speech comes later, not never."""
    reply = '{"commands": [{"name": "move_base", "args": {"command": "stop"}}], "say": "Stopping."}'
    spoken, outcome = _run(_characterwise(reply))
    assert spoken == "Stopping."
    assert outcome.commands[0]["args"]["command"] == "stop"
