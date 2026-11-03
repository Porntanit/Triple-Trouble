import os
import json
import math
import re
import sqlite3
from pathlib import Path

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename
import requests
import fitz

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "local-ollama-chat-development-key")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
MODEL = "gemma3:1b"
EMBEDDING_MODEL = "nomic-embed-text"
OLLAMA_EMBED_URL = "http://localhost:11434/api/embed"
UPLOAD_FOLDER = Path(app.root_path) / "uploads"
INDEX_PATH = Path(app.root_path) / "document_index.sqlite3"
ALLOWED_EXTENSIONS = {"pdf", "txt", "docx", "md"}
CHUNK_WORDS = 180
CHUNK_OVERLAP = 30
RETRIEVAL_LIMIT = 5


def db_connect():
    connection = sqlite3.connect(INDEX_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("""CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY, filename TEXT NOT NULL, page INTEGER NOT NULL,
        content TEXT NOT NULL, embedding TEXT NOT NULL)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS documents (
        filename TEXT PRIMARY KEY, status TEXT NOT NULL, chunk_count INTEGER NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT '')""")
    return connection


def split_chunks(text):
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + CHUNK_WORDS, len(words))
        passage = " ".join(words[start:end]).strip()
        if passage:
            chunks.append(passage)
        if end == len(words):
            break
        start = end - CHUNK_OVERLAP
    return chunks


def ollama_embeddings(texts):
    response = requests.post(OLLAMA_EMBED_URL,
                             json={"model": EMBEDDING_MODEL, "input": texts}, timeout=120)
    response.raise_for_status()
    data = response.json()
    embeddings = data.get("embeddings") if isinstance(data, dict) else None
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise ValueError("Ollama returned an unexpected embedding response.")
    return embeddings


def index_pdf(path):
    connection = db_connect()
    try:
        pages = []
        with fitz.open(path) as pdf:
            for page_number, page in enumerate(pdf, start=1):
                pages.extend((page_number, chunk) for chunk in split_chunks(page.get_text("text")))
        if not pages:
            connection.execute("DELETE FROM chunks WHERE filename = ?", (path.name,))
            connection.execute("INSERT OR REPLACE INTO documents(filename,status,chunk_count,error) VALUES(?,?,?,?)",
                               (path.name, "no_text", 0, "No extractable text found in this PDF."))
            connection.commit()
            return 0
        vectors = ollama_embeddings([chunk for _, chunk in pages])
        connection.execute("DELETE FROM chunks WHERE filename = ?", (path.name,))
        connection.executemany("INSERT INTO chunks(filename,page,content,embedding) VALUES(?,?,?,?)",
                               [(path.name, page, chunk, json.dumps(vector))
                                for (page, chunk), vector in zip(pages, vectors)])
        connection.execute("INSERT OR REPLACE INTO documents(filename,status,chunk_count,error) VALUES(?,?,?,?)",
                           (path.name, "indexed", len(pages), ""))
        connection.commit()
        return len(pages)
    except Exception as error:
        connection.execute("DELETE FROM chunks WHERE filename = ?", (path.name,))
        connection.execute("INSERT OR REPLACE INTO documents(filename,status,chunk_count,error) VALUES(?,?,?,?)",
                           (path.name, "error", 0, str(error)[:240]))
        connection.commit()
        return 0
    finally:
        connection.close()


def sync_pdf_index():
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    connection = db_connect()
    rows = {row["filename"]: row for row in connection.execute("SELECT * FROM documents")}
    connection.close()
    current = {p.name: p for p in UPLOAD_FOLDER.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"}
    connection = db_connect()
    for old_name in set(rows) - set(current):
        connection.execute("DELETE FROM chunks WHERE filename = ?", (old_name,))
        connection.execute("DELETE FROM documents WHERE filename = ?", (old_name,))
    connection.commit()
    connection.close()
    for name, path in current.items():
        if name not in rows or rows[name]["status"] == "error":
            index_pdf(path)


def retrieve_passages(question):
    query_vector = ollama_embeddings([question])[0]
    connection = db_connect()
    chunks = connection.execute("SELECT filename,page,content,embedding FROM chunks").fetchall()
    connection.close()
    def similarity(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        norms = math.sqrt(sum(x*x for x in a) * sum(y*y for y in b))
        return dot / norms if norms else 0
    scored = sorted(((similarity(query_vector, json.loads(row["embedding"])), row) for row in chunks),
                    key=lambda item: item[0], reverse=True)
    return [row for score, row in scored[:RETRIEVAL_LIMIT] if score > 0]


def uploaded_files():
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    files = []
    for path in UPLOAD_FOLDER.iterdir():
        if path.is_file():
            files.append({"name": path.name, "size": path.stat().st_size})
    return sorted(files, key=lambda file: file["name"].lower())


def format_file_size(size):
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


app.jinja_env.filters["filesize"] = format_file_size


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/documents")
def documents():
    sync_pdf_index()
    connection = db_connect()
    statuses = {row["filename"]: dict(row) for row in connection.execute("SELECT * FROM documents")}
    connection.close()
    files = uploaded_files()
    for file in files:
        file["index"] = statuses.get(file["name"])
    return render_template("documents.html", files=files)


@app.get("/documents/file/<path:filename>")
def uploaded_document(filename):
    if (not filename or Path(filename).name != filename or "/" in filename or "\\" in filename
            or Path(filename).suffix.lower().lstrip(".") not in ALLOWED_EXTENSIONS):
        abort(404)
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=False)


@app.post("/documents/upload")
def upload_document():
    file = request.files.get("file")
    if file is None or not file.filename:
        flash("Choose a document to upload.", "error")
        return redirect(url_for("documents"))

    original_name = file.filename
    if "/" in original_name or "\\" in original_name:
        flash("The filename must not contain a folder path.", "error")
        return redirect(url_for("documents"))

    safe_name = secure_filename(original_name)
    extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if not safe_name or extension not in ALLOWED_EXTENSIONS:
        flash("Allowed file types are PDF, TXT, DOCX, and MD.", "error")
        return redirect(url_for("documents"))

    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    destination = (UPLOAD_FOLDER / safe_name).resolve()
    if destination.parent != UPLOAD_FOLDER.resolve():
        flash("Invalid filename.", "error")
        return redirect(url_for("documents"))
    if destination.exists():
        flash("A file with that name already exists. Rename the document and try again.", "error")
        return redirect(url_for("documents"))

    try:
        file.save(destination)
    except OSError:
        app.logger.exception("Document upload failed")
        flash("The document could not be saved. Check the uploads folder and try again.", "error")
        return redirect(url_for("documents"))
    if destination.suffix.lower() == ".pdf":
        count = index_pdf(destination)
        connection = db_connect()
        status = connection.execute("SELECT status,error FROM documents WHERE filename = ?", (safe_name,)).fetchone()
        connection.close()
        if status and status["status"] == "indexed":
            flash(f"Indexed {safe_name}: {count} searchable chunks.", "success")
        elif status and status["status"] == "no_text":
            flash(f"Uploaded {safe_name}, but it contains no extractable text to index.", "error")
        else:
            flash(f"Uploaded {safe_name}, but indexing failed: {status['error'] if status else 'unknown error'}", "error")
        return redirect(url_for("documents"))
    flash(f"Uploaded {safe_name}.", "success")
    return redirect(url_for("documents"))


@app.post("/documents/delete/<path:filename>")
def delete_document(filename):
    if not filename or Path(filename).name != filename or "/" in filename or "\\" in filename:
        flash("Invalid filename.", "error")
        return redirect(url_for("documents"))
    destination = (UPLOAD_FOLDER / filename).resolve()
    if destination.parent != UPLOAD_FOLDER.resolve() or not destination.is_file():
        flash("That document was not found.", "error")
        return redirect(url_for("documents"))
    try:
        destination.unlink()
    except OSError:
        app.logger.exception("Document deletion failed")
        flash("The document could not be deleted. Try again.", "error")
        return redirect(url_for("documents"))
    connection = db_connect()
    connection.execute("DELETE FROM chunks WHERE filename = ?", (filename,))
    connection.execute("DELETE FROM documents WHERE filename = ?", (filename,))
    connection.commit()
    connection.close()
    flash(f"Deleted {filename}.", "success")
    return redirect(url_for("documents"))


@app.errorhandler(413)
def upload_too_large(_error):
    flash("The upload is too large. Maximum file size is 16 MB.", "error")
    return redirect(url_for("documents"))


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True)
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list) or not messages:
        return jsonify(error="Send a conversation with at least one message."), 400

    # Accept only chat messages so arbitrary Ollama options cannot be injected.
    safe_messages = []
    for message in messages:
        if not isinstance(message, dict):
            return jsonify(error="Each message must have a role and content."), 400
        role, content = message.get("role"), message.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            return jsonify(error="Messages must use the user or assistant role and text content."), 400
        safe_messages.append({"role": role, "content": content})

    try:
        last_question = next((m["content"] for m in reversed(safe_messages) if m["role"] == "user"), "")
        sources = []
        sync_pdf_index()
        connection = db_connect()
        filenames = sorted((file["name"] for file in uploaded_files()), key=str.lower)
        connection.close()
        if re.search(r"\b(what|which)\b.*\b(papers?|documents?|files?)\b.*\b(collection|uploaded|have|available)\b|\b(papers?|documents?)\s+(in|inside)\s+(my|the)\s+(document\s+)?collection\b", last_question, re.I):
            answer = ("Uploaded PDF papers: " + ", ".join(filenames)) if filenames else "There are no indexed PDF papers in the document collection."
            return jsonify(message={"role": "assistant", "content": answer})
        if filenames and last_question:
            passages = retrieve_passages(last_question)
            if passages:
                sources = sorted({(row["filename"], row["page"]) for row in passages})
                context = "\n\n".join(f"Source: {row['filename']}, page {row['page']}\nPassage: {row['content']}" for row in passages)
                safe_messages.insert(0, {"role": "system", "content": (
                    "Answer the user's question using the provided document passages. Cite supporting claims as "
                    "[filename, page N]. Use only these exact source filenames and page numbers. If the passages "
                    "do not support an answer, say so. Never invent citations.\n\nDOCUMENT PASSAGES:\n" + context)})
            else:
                safe_messages.insert(0, {"role": "system", "content": "No relevant passages were found in the indexed PDFs. Say that the document collection does not provide evidence for the answer. Do not invent sources or citations."})
        response = requests.post(
            OLLAMA_CHAT_URL,
            json={"model": MODEL, "messages": safe_messages, "stream": False},
            timeout=120,
        )
        response.raise_for_status()
        result = response.json()
        message = result.get("message") if isinstance(result, dict) else None
        answer = message.get("content") if isinstance(message, dict) else None
        if not isinstance(answer, str):
            return jsonify(error="Ollama returned an unexpected response."), 502
        return jsonify(message={"role": "assistant", "content": answer, "sources": [
            {"filename": filename, "page": page} for filename, page in sources
        ]})
    except requests.exceptions.JSONDecodeError:
        return jsonify(error="Ollama returned invalid JSON."), 502
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else "unknown"
        return jsonify(error=f"Ollama returned an HTTP error ({status}). Check that gemma3:1b is available."), 502
    except requests.RequestException:
        app.logger.exception("Ollama request failed")
        return jsonify(error="Could not reach Ollama. Check that Ollama is running and gemma3:1b is available."), 502


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
