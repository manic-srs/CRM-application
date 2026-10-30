"""AI Assistant API: chat with the CRM in plain words (see app/assistant.py for how it works)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import assistant
from app.database import get_db

router = APIRouter(prefix="/api/assistant", tags=["AI Assistant"])


class ChatRequest(BaseModel):
    messages: list[dict] = Field(default_factory=list, max_length=200)  # the conversation so far (as returned last time)
    message: str = Field(..., min_length=1, max_length=4000)


class ConfirmRequest(BaseModel):
    messages: list[dict] = Field(default_factory=list, max_length=200)
    pending: dict
    confirmed: bool


def require_enabled():
    if not assistant.enabled():
        raise HTTPException(status_code=503, detail="The AI Assistant isn't set up yet. "
                            "Add OPENAI_API_KEY to the .env file and restart the app (docker compose up -d).")


@router.get("/status")
def status():
    """Is the assistant switched on? (The page shows a setup message when it isn't.)"""
    cfg = assistant.settings()
    return {"enabled": bool(cfg["key"]), "model": cfg["model"]}


@router.post("/chat")
def chat(data: ChatRequest, db: Session = Depends(get_db)):
    """Send one message. Returns the updated conversation, the reply, links to records it touched,
    and 'pending' when an action is waiting for the user's Confirm."""
    require_enabled()
    history = assistant.clean_history(data.messages)
    history.append({"role": "user", "content": data.message.strip()})
    return assistant.converse(db, history)


@router.post("/confirm")
def confirm(data: ConfirmRequest, db: Session = Depends(get_db)):
    """Confirm (or cancel) the action the assistant asked about."""
    require_enabled()
    history = [m for m in data.messages if isinstance(m, dict)]
    return assistant.resolve(db, history, data.pending, data.confirmed)
