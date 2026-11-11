import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from fastapi_users.exceptions import FastAPIUsersException

from app.api.sessions import get_interview_manager
from app.auth.users import UserManager, get_jwt_strategy, get_user_manager
from app.services.interviews import InterviewManager, InterviewNotActiveError
from app.voice.session import VoiceSession
from app.voice.stt import SpeechToText, get_stt
from app.voice.tts import TextToSpeech, get_tts

logger = logging.getLogger("coach.api")
router = APIRouter()

WS_UNAUTHORIZED = 4401  # application close codes (4000-4999)
WS_NOT_ACTIVE = 4409


@router.websocket("/ws/sessions/{session_id}")
async def voice_interview(
    websocket: WebSocket,
    session_id: uuid.UUID,
    token: str,  # browsers can't set headers on a WebSocket, so the JWT comes as ?token=
    manager: Annotated[InterviewManager, Depends(get_interview_manager)],
    user_manager: Annotated[UserManager, Depends(get_user_manager)],
    stt: Annotated[SpeechToText, Depends(get_stt)],
    tts: Annotated[TextToSpeech, Depends(get_tts)],
) -> None:
    """Client -> server: binary audio frames (a WAV utterance) then {"type": "audio_end"};
    {"type": "text_answer", "text": ...}; {"type": "end_interview"}. See app/voice/session.py for replies."""
    try:
        user = await get_jwt_strategy().read_token(token, user_manager)
    except FastAPIUsersException:
        user = None
    if user is None or not user.is_active:
        await websocket.close(code=WS_UNAUTHORIZED)
        return

    await websocket.accept()
    session = VoiceSession(websocket, manager, user.id, session_id, stt, tts)
    try:
        await session.open()
    except InterviewNotActiveError:
        await websocket.close(code=WS_NOT_ACTIVE, reason="Interview is not in progress")
        return

    audio = bytearray()
    try:
        while not session.done:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                audio.extend(message["bytes"])
                continue
            try:
                data = json.loads(message.get("text") or "{}")
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid message"})
                continue
            match data.get("type"):
                case "audio_end":
                    chunk, audio = bytes(audio), bytearray()
                    await session.handle_audio(chunk)
                case "text_answer":
                    await session.handle_text(str(data.get("text", "")))
                case "end_interview":
                    await session.handle_end()
                case other:
                    await websocket.send_json({"type": "error", "message": f"Unknown message type: {other}"})
        if session.done:
            await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
    except WebSocketDisconnect:
        # The interview stays active: the client can reconnect and continue (or answer over REST)
        logger.info("Voice client disconnected from %s", session_id)
