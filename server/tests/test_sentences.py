from sentences import SentenceAccumulator


def feed(pieces: list[str]) -> tuple[list[str], str | None]:
    """Run pieces through the accumulator the way a token stream arrives."""
    accumulator = SentenceAccumulator()
    out = []
    for piece in pieces:
        out.extend(accumulator.add(piece))
    return out, accumulator.finish()


def test_sentence_is_released_as_soon_as_it_completes() -> None:
    """The point of streaming: speak sentence one without waiting for two."""
    sentences, remainder = feed(["I am feeling ", "quite well today. ", "How about you?"])
    assert sentences == ["I am feeling quite well today."]
    assert remainder == "How about you?"


def test_tokens_arriving_one_character_at_a_time() -> None:
    sentences, remainder = feed(list("The kettle is on. Tea will be ready soon."))
    assert sentences == ["The kettle is on."]
    assert remainder == "Tea will be ready soon."


def test_abbreviations_do_not_end_a_sentence() -> None:
    sentences, remainder = feed(["I spoke to Dr. Alvarez this morning. ", "All fine."])
    assert sentences == ["I spoke to Dr. Alvarez this morning."]
    assert remainder == "All fine."


def test_very_short_fragments_are_held_back() -> None:
    """"Hi." alone is not worth its own synthesis call."""
    sentences, remainder = feed(["Hi. ", "It is good to see you again."])
    assert sentences == []
    assert remainder == "Hi. It is good to see you again."


def test_question_and_exclamation_end_sentences() -> None:
    sentences, _ = feed(["Are you doing alright? ", "I hope so! ", "x"])
    assert sentences == ["Are you doing alright?", "I hope so!"]


def test_closing_quote_stays_with_its_sentence() -> None:
    sentences, _ = feed(['She said "that is enough." ', "Then she left the room."])
    assert sentences[0] == 'She said "that is enough."'


def test_finish_returns_nothing_when_drained() -> None:
    accumulator = SentenceAccumulator()
    list(accumulator.add("This is a whole sentence. "))
    assert accumulator.finish() is None


def test_whitespace_only_stream_yields_nothing() -> None:
    sentences, remainder = feed(["   ", "\n"])
    assert sentences == []
    assert remainder is None
