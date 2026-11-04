"""AI Assistant API: chat with the CRM in plain words (see app/assistant.py for how it works).

Every user's chats are saved (the history panel): list, open, rename and delete them. Files attached in the chat
are uploaded first (POST /files) and their ids sent with the message. Every role (Admin, Manager, Salesperson) can
use the assistant; what it can do follows the user's own permissions.
"""
import base64
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import assistant, assistant_store as store
from app.database import get_db
from app.models import AssistantConversation, AssistantFile
from app.security import acting_user

router = APIRouter(prefix="/api/assistant", tags=["AI Assistant"])

MAX_FILE_TEXT_TO_AI = 15_000  # characters of each attached document the AI reads with the message


class ChatRequest(BaseModel):
    conversation_id: int | None = None  # a saved chat (its history is loaded on the server); none = a new chat
    messages: list[dict] = Field(default_factory=list, max_length=200)  # without conversation_id: the history so far
    message: str = Field(..., min_length=1, max_length=20_000)  # room for pasted emails, signatures and lists
    file_ids: list[int] = Field(default_factory=list, max_length=store.MAX_FILES_PER_MESSAGE)


class ConfirmRequest(BaseModel):
    conversation_id: int | None = None
    messages: list[dict] = Field(default_factory=list, max_length=200)
    pending: dict | None = None
    confirmed: bool


class Rename(BaseModel):
    title: str = Field(..., min_length=1, max_length=store.TITLE_MAX)


def require_enabled():
    if not assistant.enabled():
        raise HTTPException(status_code=503, detail="The AI Assistant isn't set up yet. "
                            "Add OPENAI_API_KEY to the .env file and restart the app (docker compose up -d).")


@router.get("/status")
def status():
    """Is the assistant switched on? (The page shows a setup message when it isn't.)"""
    cfg = assistant.settings()
    return {"enabled": bool(cfg["key"]), "model": cfg["model"]}


# ---------- saved chats (history panel) ----------

@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db)):
    """The user's chats, most recent first."""
    rows = db.scalars(select(AssistantConversation).where(AssistantConversation.user_id == acting_user().id)
                      .order_by(AssistantConversation.updated_at.desc(), AssistantConversation.id.desc())
                      .limit(200)).all()
    return [store.conversation_out(c) for c in rows]


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    return store.conversation_out(store.get_conversation(db, conversation_id), full=True)


@router.patch("/conversations/{conversation_id}")
def rename_conversation(conversation_id: int, data: Rename, db: Session = Depends(get_db)):
    conv = store.get_conversation(db, conversation_id)
    title = " ".join(data.title.split())
    if not title:
        raise HTTPException(status_code=422, detail="Enter a name for the chat")
    conv.title = title
    db.commit()
    db.refresh(conv)
    return store.conversation_out(conv)


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conv = store.get_conversation(db, conversation_id)
    for f in db.scalars(select(AssistantFile).where(AssistantFile.conversation_id == conv.id)).all():
        db.delete(f)
    db.delete(conv)
    db.commit()
    return {"deleted": conversation_id}


# ---------- files ----------

@router.post("/files", status_code=201)
async def upload_file(file: UploadFile = File(...), conversation_id: int | None = Form(None),
                      db: Session = Depends(get_db)):
    """Attach a file to the chat: PDF, Word, Excel, PowerPoint, CSV, text, HTML, email or an image, up to 10 MB.
    Documents are read as text; images are shown to the AI. Returns the id to send with the message."""
    data = await file.read(store.MAX_FILE_BYTES + 1)
    return store.file_out(store.save_file(db, file.filename or "file", data, conversation_id))


def _with_files(message: str, files: list[AssistantFile]) -> tuple[str | list, str]:
    """(what the AI reads now, what is kept in the saved history). Documents go in as text; images as pictures
    for this message only (the history keeps a short mention, so they aren't sent again with every message)."""
    text = message
    for f in files:
        if f.kind == "text":
            body = (f.text or "")[:MAX_FILE_TEXT_TO_AI]
            more = "\n[...the rest of the file is cut off]" if len(f.text or "") > MAX_FILE_TEXT_TO_AI else ""
            text += f"\n\n[Attached file: {f.filename}]\n{body}{more}\n[End of {f.filename}]"
        else:
            text += f"\n\n[Attached image: {f.filename}]"
    images = [f for f in files if f.kind == "image"]
    if not images:
        return text, text
    parts = [{"type": "text", "text": text}]
    for f in images:
        url = f"data:{f.content_type};base64,{base64.b64encode(f.data).decode()}"
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts, text


def _close_cards(chat: list[dict]) -> list[dict]:
    return [{**m, "pending": None} for m in chat]


def _ai_entry(out: dict) -> dict:
    return {"from": "ai", "text": out["reply"], "links": out.get("links", []), "pending": out.get("pending"),
            "suggestions": out.get("suggestions", [])}


@router.post("/chat")
def chat(data: ChatRequest, db: Session = Depends(get_db)):
    """Send one message. Returns the reply, links to records it touched, suggested next requests, 'pending' when
    an action is waiting for the user's Confirm, and the saved chat (conversation)."""
    require_enabled()
    message = data.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Type a message")
    if data.conversation_id is not None:
        conv = store.get_conversation(db, data.conversation_id)
        stored, chat_log = store.load(conv)
        history = assistant.clean_history(stored)
    else:
        conv, chat_log = None, []
        history = assistant.clean_history(data.messages)
    files = store.own_files(db, data.file_ids) if data.file_ids else []
    for_ai, for_history = _with_files(message, files)
    history.append({"role": "user", "content": for_ai})
    hello = None if files else assistant.greeting_reply(message)
    if hello:  # "hi" / "hello": greeted straight away, without asking the AI
        out = {"messages": [*history, {"role": "assistant", "content": hello}], "reply": hello, "links": [], "done": [],
               "pending": None, "suggestions": []}
    else:
        out = assistant.converse(db, history)
    # the saved history keeps the text version of this message (images aren't stored in it)
    out["messages"] = [{**m, "content": for_history} if m.get("role") == "user" and m.get("content") is for_ai else m
                       for m in out["messages"]]
    if conv is None:
        conv = AssistantConversation(user_id=acting_user().id, title=store.new_title(message))
        db.add(conv)
        db.flush()
    chat_log = _close_cards(chat_log)
    chat_log.append({"from": "me", "text": message, "files": [store.file_out(f) for f in files]})
    chat_log.append(_ai_entry(out))
    for f in files:
        f.conversation_id = conv.id
    store.store(conv, out["messages"], chat_log, out.get("pending"))
    db.commit()
    db.refresh(conv)
    return {**out, "conversation": store.conversation_out(conv), "chat": chat_log}


@router.post("/confirm")
def confirm(data: ConfirmRequest, db: Session = Depends(get_db)):
    """Confirm (or cancel) the action the assistant asked about."""
    require_enabled()
    if data.conversation_id is None:  # the browser holds the history (older clients and the API)
        history = [m for m in data.messages if isinstance(m, dict)]
        return assistant.resolve(db, history, data.pending or {}, data.confirmed)
    conv = store.get_conversation(db, data.conversation_id)
    history, chat_log = store.load(conv)
    pending = json.loads(conv.pending) if conv.pending else None  # the saved action, not what the browser sent
    if pending is None:
        raise HTTPException(status_code=400, detail="This action is no longer waiting for confirmation")
    out = assistant.resolve(db, history, pending, data.confirmed)
    chat_log = _close_cards(chat_log)
    chat_log.append({"from": "me", "text": "Confirm" if data.confirmed else "Cancel", "small": True})
    chat_log.append(_ai_entry(out))
    store.store(conv, out["messages"], chat_log, out.get("pending"))
    db.commit()
    db.refresh(conv)
    return {**out, "conversation": store.conversation_out(conv), "chat": chat_log}
