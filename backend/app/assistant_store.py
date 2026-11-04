"""AI Assistant storage: each user's saved conversations (the history panel) and the files they attach.

Files: the text is read out of documents when they are uploaded (PDF, Word, Excel, PowerPoint, CSV, text, HTML,
email), so the AI reads the text. Images (PNG, JPG, WEBP, GIF) are kept and shown to the AI as pictures (business
cards, screenshots...). Nothing in a file is ever run.
"""
import csv
import html
import io
import json
import re
import zipfile
from xml.etree import ElementTree

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AssistantConversation, AssistantFile
from app.security import acting_user

MAX_FILE_BYTES = 10 * 1024 * 1024       # per file
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 60_000                 # kept per file
MAX_FILES_PER_MESSAGE = 5
MAX_UNZIPPED_BYTES = 40 * 1024 * 1024   # Word / Excel / PowerPoint parts (protects against zip bombs)
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
TEXT_TYPES = {".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv", ".tsv": "text/tab-separated-values",
              ".json": "application/json", ".html": "text/html", ".htm": "text/html", ".eml": "message/rfc822",
              ".xml": "application/xml", ".log": "text/plain"}
DOC_TYPES = {".pdf": "application/pdf",
             ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
SUPPORTED = "PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), CSV, text, HTML, email (.eml) and images (PNG, JPG, WEBP, GIF)"
TITLE_MAX = 120


# ---------- reading files ----------

def _extension(filename: str) -> str:
    match = re.search(r"\.[A-Za-z0-9]+$", filename or "")
    return match.group(0).lower() if match else ""


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig",):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1")


def _zip_part(archive: zipfile.ZipFile, name: str) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > MAX_UNZIPPED_BYTES:
        raise HTTPException(status_code=400, detail="This file is too large to read")
    return archive.read(name)


def _xml_text(data: bytes, paragraph_tag: str) -> str:
    root = ElementTree.fromstring(data)
    lines = []
    for para in root.iter():
        if para.tag.endswith(paragraph_tag):
            text = "".join(node.text or "" for node in para.iter() if node.tag.endswith("}t"))
            if text.strip():
                lines.append(text.strip())
    return "\n".join(lines)


def _pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # the image was built before pypdf was added: rebuild (docker compose up -d --build)
        raise HTTPException(status_code=500, detail="Reading PDFs needs the pypdf package. Rebuild the app "
                            "(docker compose up -d --build).") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise HTTPException(status_code=400, detail="This PDF is password-protected. Upload a copy without a password.")
        pages = []
        for number, page in enumerate(reader.pages[:200], start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(f"[Page {number}]\n{text}")
        return "\n\n".join(pages)
    except HTTPException:
        raise
    except Exception as exc:  # pypdf raises many kinds of errors for damaged files
        raise HTTPException(status_code=400, detail="This PDF could not be read. It may be damaged.") from exc


def _xlsx(data: bytes) -> str:
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    for sheet in book.worksheets[:10]:
        rows = []
        for row in sheet.iter_rows(values_only=True, max_row=2000):
            if any(v not in (None, "") for v in row):
                rows.append(row)
        if rows:
            buffer = io.StringIO()
            csv.writer(buffer).writerows(["" if v is None else v for v in r] for r in rows)
            out.append(f"[Sheet {sheet.title}]\n{buffer.getvalue().strip()}")
    return "\n\n".join(out)


def read_text(filename: str, data: bytes) -> str:
    """The readable text of a document (raises 400 for a type or file that can't be read)."""
    ext = _extension(filename)
    try:
        if ext == ".pdf":
            return _pdf(data)
        if ext in (".docx", ".pptx", ".xlsx"):
            if not zipfile.is_zipfile(io.BytesIO(data)):
                raise HTTPException(status_code=400, detail="This file is damaged or isn't really a "
                                    f"{ext[1:].upper()} file")
            if ext == ".xlsx":
                return _xlsx(data)
            archive = zipfile.ZipFile(io.BytesIO(data))
            if ext == ".docx":
                return _xml_text(_zip_part(archive, "word/document.xml"), "}p")
            slides = sorted((n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                            key=lambda n: int(re.search(r"\d+", n.rsplit("/", 1)[1]).group()))
            return "\n\n".join(f"[Slide {i}]\n{_xml_text(_zip_part(archive, n), '}p')}"
                               for i, n in enumerate(slides[:200], start=1))
        if ext in TEXT_TYPES:
            text = _decode(data)
            if ext in (".html", ".htm"):
                text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
                text = html.unescape(re.sub(r"<[^>]+>", " ", text))
            return text
    except HTTPException:
        raise
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="This file could not be read. It may be damaged.") from exc
    raise HTTPException(status_code=400, detail=f"This file type can't be read. Attach {SUPPORTED}.")


def save_file(db: Session, filename: str, data: bytes, conversation_id: int | None = None) -> AssistantFile:
    me = acting_user()
    filename = re.sub(r"[\x00-\x1f/\\]+", " ", (filename or "file").strip())[-255:] or "file"
    if not data:
        raise HTTPException(status_code=400, detail="The file is empty")
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="Files can be up to 10 MB")
    if conversation_id is not None:
        get_conversation(db, conversation_id)
    ext = _extension(filename)
    if ext in IMAGE_TYPES:
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=400, detail="Images can be up to 5 MB")
        signatures = (b"\x89PNG", b"\xff\xd8\xff", b"RIFF", b"GIF8")
        if not data.startswith(signatures):
            raise HTTPException(status_code=400, detail="This file isn't a PNG, JPG, WEBP or GIF image")
        record = AssistantFile(user_id=me.id, conversation_id=conversation_id, filename=filename,
                               content_type=IMAGE_TYPES[ext], kind="image", size_bytes=len(data), data=data)
    else:
        text = re.sub(r"[ \t]+\n", "\n", read_text(filename, data)).strip()
        if not text:
            raise HTTPException(status_code=400, detail="No text could be found in this file (a scanned PDF? "
                                "Attach it as an image instead).")
        record = AssistantFile(user_id=me.id, conversation_id=conversation_id, filename=filename,
                               content_type=DOC_TYPES.get(ext) or TEXT_TYPES.get(ext, "application/octet-stream"),
                               kind="text", size_bytes=len(data), text=text[:MAX_TEXT_CHARS])
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def file_out(f: AssistantFile) -> dict:
    return {"id": f.id, "filename": f.filename, "kind": f.kind, "size_bytes": f.size_bytes,
            "chars": len(f.text or ""), "truncated": f.kind == "text" and len(f.text or "") >= MAX_TEXT_CHARS}


def own_files(db: Session, ids: list[int]) -> list[AssistantFile]:
    me = acting_user()
    ids = list(dict.fromkeys(ids))[:MAX_FILES_PER_MESSAGE + 1]
    if len(ids) > MAX_FILES_PER_MESSAGE:
        raise HTTPException(status_code=400, detail=f"Attach up to {MAX_FILES_PER_MESSAGE} files per message")
    files = db.scalars(select(AssistantFile).where(AssistantFile.id.in_(ids), AssistantFile.user_id == me.id)).all()
    if len(files) != len(ids):
        raise HTTPException(status_code=404, detail="An attached file was not found. Attach it again.")
    order = {i: n for n, i in enumerate(ids)}
    return sorted(files, key=lambda f: order[f.id])


# ---------- conversations ----------

def get_conversation(db: Session, conversation_id: int) -> AssistantConversation:
    conv = db.get(AssistantConversation, conversation_id)
    if conv is None or conv.user_id != acting_user().id:  # each user sees only their own chats
        raise HTTPException(status_code=404, detail="This chat doesn't exist")
    return conv


def new_title(message: str) -> str:
    text = " ".join((message or "").split()) or "New chat"
    return text if len(text) <= 60 else text[:57].rstrip() + "…"


def conversation_out(conv: AssistantConversation, full: bool = False) -> dict:
    out = {"id": conv.id, "title": conv.title, "created_at": conv.created_at, "updated_at": conv.updated_at}
    if full:
        out["chat"] = json.loads(conv.chat or "[]")
        out["pending"] = json.loads(conv.pending) if conv.pending else None
    return out


def load(conv: AssistantConversation) -> tuple[list[dict], list[dict]]:
    return json.loads(conv.messages or "[]"), json.loads(conv.chat or "[]")


def store(conv: AssistantConversation, messages: list[dict], chat: list[dict], pending: dict | None) -> None:
    conv.messages = json.dumps(messages[-400:])
    conv.chat = json.dumps(chat[-300:])
    conv.pending = json.dumps(pending) if pending else None
