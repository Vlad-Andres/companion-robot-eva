"""
actions/speak_handler.py — Handler for the "speak" action type.

Receives a SpeakPayload and plays synthesized speech through the speakers.

TODO: Integrate with a TTS engine (e.g. piper-tts, espeak, or a TTS API).
"""

from __future__ import annotations

from actions.action_types import Action, ActionType, SpeakPayload
from actions.base_action_handler import BaseActionHandler
from utils.logger import get_logger

log = get_logger(__name__)


class SpeakHandler(BaseActionHandler):
    """
    Handles "speak" actions by converting text to speech.

    Responsibilities:
      - Receive SpeakPayload.text from the dispatcher.
      - Convert text to audio using the TTS engine.
      - Play audio through speakers.
      - Record the spoken text in ContextManager (via callback or injected ref).

    Dependencies injected at construction:
      - context_manager: For recording robot speech in conversation history.
      - tts_engine:      TTS synthesis interface (to be implemented).
    """

    action_type = ActionType.SPEAK

    def __init__(self, context_manager=None, tts_engine=None) -> None:
        """
        Args:
            context_manager: ContextManager instance for recording robot utterances.
            tts_engine:      TTS engine stub (inject real implementation later).
        """
        self._context = context_manager
        self._tts = tts_engine

    async def handle(self, action: Action) -> None:
        """
        Execute the speak action.

        Args:
            action: Action with payload of type SpeakPayload.
        """
        payload: SpeakPayload = action.payload
        text = payload.text

        log.info("Robot speaks: %r", text)

        # TODO: Call TTS engine to synthesize and play audio.
        #       Example: await self._tts.speak(text)

        # Record what the robot said in conversation context.
        if self._context is not None:
            self._context.record_robot_speech(text)
            self._context.record_action(ActionType.SPEAK)
