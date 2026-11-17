import os
import io
import importlib.util
import json
import math
import re
import sqlite3
import secrets
from functools import wraps
from urllib.parse import urlsplit
from pathlib import Path

from flask import (
    Flask,
    send_file,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename
import requests
import fitz
import storage
import nutrition
import calories
import food_images

app = Flask(__name__)
DATA_DIR = Path(os.environ.get("TT_DATA_DIR", app.root_path)).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
# Persist a random signing key across local restarts; do not share this file.
key_path = DATA_DIR / ".session-key"
if not os.environ.get("FLASK_SECRET_KEY") and not key_path.exists():
    try:
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(secrets.token_hex(32))
    except FileExistsError:
        pass
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or key_path.read_text().strip()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict")
NUTRITION_PATH = DATA_DIR / "nutrition.sqlite3"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
MODEL = "gemma3:1b"
EMBEDDING_MODEL = "nomic-embed-text"
OLLAMA_EMBED_URL = "http://localhost:11434/api/embed"
UPLOAD_FOLDER = DATA_DIR / "uploads"
INDEX_PATH = DATA_DIR / "document_index.sqlite3"
ALLOWED_EXTENSIONS = {"pdf", "txt", "docx", "md"}
CHUNK_WORDS = 180
CHUNK_OVERLAP = 30
RETRIEVAL_LIMIT = 5


def db_connect():
    connection = sqlite3.connect(INDEX_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY, filename TEXT NOT NULL, page INTEGER NOT NULL,
        content TEXT NOT NULL, embedding TEXT NOT NULL)"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS documents (
        filename TEXT PRIMARY KEY, status TEXT NOT NULL, chunk_count INTEGER NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT '')"""
    )
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
    response = requests.post(
        OLLAMA_EMBED_URL, json={"model": EMBEDDING_MODEL, "input": texts}, timeout=120
    )
    response.raise_for_status()
    data = response.json()
    embeddings = data.get("embeddings") if isinstance(data, dict) else None
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise ValueError("Ollama returned an unexpected embedding response.")
    for vector in embeddings:
        if (
            not isinstance(vector, list)
            or not vector
            or any(type(n) not in (int, float) or not math.isfinite(n) for n in vector)
            or not any(vector)
        ):
            raise ValueError("Ollama returned an invalid embedding vector.")
    if len({len(v) for v in embeddings}) != 1:
        raise ValueError("Ollama returned inconsistent embedding dimensions.")
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
            connection.execute(
                "INSERT OR REPLACE INTO documents(filename,status,chunk_count,error) VALUES(?,?,?,?)",
                (path.name, "no_text", 0, "No extractable text found in this PDF."),
            )
            connection.commit()
            return 0
        vectors = ollama_embeddings([chunk for _, chunk in pages])
        connection.execute("DELETE FROM chunks WHERE filename = ?", (path.name,))
        connection.executemany(
            "INSERT INTO chunks(filename,page,content,embedding) VALUES(?,?,?,?)",
            [
                (path.name, page, chunk, json.dumps(vector))
                for (page, chunk), vector in zip(pages, vectors)
            ],
        )
        connection.execute(
            "INSERT OR REPLACE INTO documents(filename,status,chunk_count,error) VALUES(?,?,?,?)",
            (path.name, "indexed", len(pages), ""),
        )
        connection.commit()
        return len(pages)
    except Exception as error:
        connection.execute("DELETE FROM chunks WHERE filename = ?", (path.name,))
        connection.execute(
            "INSERT OR REPLACE INTO documents(filename,status,chunk_count,error) VALUES(?,?,?,?)",
            (path.name, "error", 0, str(error)[:240]),
        )
        connection.commit()
        return 0
    finally:
        connection.close()


def sync_pdf_index():
    # Opening an empty collection should not require writing to disk.
    if not UPLOAD_FOLDER.exists():
        return
    connection = db_connect()
    rows = {row["filename"]: row for row in connection.execute("SELECT * FROM documents")}
    connection.close()
    current = {
        p.name: p for p in UPLOAD_FOLDER.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"
    }
    connection = db_connect()
    for old_name in set(rows) - set(current):
        connection.execute("DELETE FROM chunks WHERE filename = ?", (old_name,))
        connection.execute("DELETE FROM documents WHERE filename = ?", (old_name,))
    connection.commit()
    connection.close()
    for name, path in current.items():
        if name not in rows:
            index_pdf(path)


def retrieve_passages(question):
    query_vector = ollama_embeddings([question])[0]
    connection = db_connect()
    chunks = connection.execute("SELECT filename,page,content,embedding FROM chunks").fetchall()
    connection.close()

    def similarity(a, b):
        if len(a) != len(b):
            raise ValueError(
                "Embedding dimensions changed. Delete and upload the PDF again to rebuild its index."
            )
        dot = sum(x * y for x, y in zip(a, b))
        norms = math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))
        return dot / norms if norms else 0

    scored = sorted(
        ((similarity(query_vector, json.loads(row["embedding"])), row) for row in chunks),
        key=lambda item: item[0],
        reverse=True,
    )
    return [row for score, row in scored[:RETRIEVAL_LIMIT] if score >= 0.25]


def uploaded_files():
    if not UPLOAD_FOLDER.exists():
        return []
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


@app.get("/knowledge")
def knowledge_documents():
    try:
        sync_pdf_index()
        connection = db_connect()
        try:
            statuses = {
                row["filename"]: dict(row) for row in connection.execute("SELECT * FROM documents")
            }
        finally:
            connection.close()
        files = uploaded_files()
        for file in files:
            file["index"] = statuses.get(file["name"])
        return render_template("documents.html", files=files)
    except (OSError, sqlite3.Error) as error:
        app.logger.exception("Document collection storage unavailable")
        full = getattr(error, "errno", None) == 28 or "full" in str(error).lower()
        message = (
            "Your disk is full. Free some space on this Mac, then reload this page. "
            "Document storage is temporarily unavailable."
            if full
            else "Document storage is unavailable. Check the local data folder's permissions "
            "and available disk space, then reload this page."
        )
        return render_template("documents.html", files=[], collection_error=message), 503


@app.get("/documents/file/<path:filename>")
def uploaded_document(filename):
    if (
        not filename
        or Path(filename).name != filename
        or "/" in filename
        or "\\" in filename
        or Path(filename).suffix.lower().lstrip(".") not in ALLOWED_EXTENSIONS
    ):
        abort(404)
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=False)


@app.post("/documents/upload")
def upload_document():
    file = request.files.get("file")
    if file is None or not file.filename:
        flash("Choose a document to upload.", "error")
        return redirect(url_for("knowledge_documents"))

    original_name = file.filename
    if "/" in original_name or "\\" in original_name:
        flash("The filename must not contain a folder path.", "error")
        return redirect(url_for("knowledge_documents"))

    safe_name = secure_filename(original_name)
    extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if not safe_name or extension not in ALLOWED_EXTENSIONS:
        flash("Allowed file types are PDF, TXT, DOCX, and MD.", "error")
        return redirect(url_for("knowledge_documents"))

    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    destination = (UPLOAD_FOLDER / safe_name).resolve()
    if destination.parent != UPLOAD_FOLDER.resolve():
        flash("Invalid filename.", "error")
        return redirect(url_for("knowledge_documents"))
    if destination.exists():
        flash("A file with that name already exists. Rename the document and try again.", "error")
        return redirect(url_for("knowledge_documents"))

    try:
        file.save(destination)
    except OSError:
        app.logger.exception("Document upload failed")
        flash("The document could not be saved. Check the uploads folder and try again.", "error")
        return redirect(url_for("knowledge_documents"))
    if destination.suffix.lower() == ".pdf":
        count = index_pdf(destination)
        connection = db_connect()
        status = connection.execute(
            "SELECT status,error FROM documents WHERE filename = ?", (safe_name,)
        ).fetchone()
        connection.close()
        if status and status["status"] == "indexed":
            flash(f"Indexed {safe_name}: {count} searchable chunks.", "success")
        elif status and status["status"] == "no_text":
            flash(f"Uploaded {safe_name}, but it contains no extractable text to index.", "error")
        else:
            flash(
                f"Uploaded {safe_name}, but indexing failed: {status['error'] if status else 'unknown error'}",
                "error",
            )
        return redirect(url_for("knowledge_documents"))
    flash(f"Uploaded {safe_name}.", "success")
    return redirect(url_for("knowledge_documents"))


@app.post("/documents/delete/<path:filename>")
def delete_document(filename):
    if not filename or Path(filename).name != filename or "/" in filename or "\\" in filename:
        flash("Invalid filename.", "error")
        return redirect(url_for("knowledge_documents"))
    destination = (UPLOAD_FOLDER / filename).resolve()
    if destination.parent != UPLOAD_FOLDER.resolve() or not destination.is_file():
        flash("That document was not found.", "error")
        return redirect(url_for("knowledge_documents"))
    try:
        destination.unlink()
    except OSError:
        app.logger.exception("Document deletion failed")
        flash("The document could not be deleted. Try again.", "error")
        return redirect(url_for("knowledge_documents"))
    connection = db_connect()
    connection.execute("DELETE FROM chunks WHERE filename = ?", (filename,))
    connection.execute("DELETE FROM documents WHERE filename = ?", (filename,))
    connection.commit()
    connection.close()
    flash(f"Deleted {filename}.", "success")
    return redirect(url_for("knowledge_documents"))


@app.errorhandler(413)
def upload_too_large(_error):
    if request.path.startswith("/api/"):
        return jsonify(error="Image upload is too large. Use JPG, PNG or WebP up to 8 MB."), 413
    flash("The upload is too large. Maximum file size is 16 MB.", "error")
    return redirect(url_for("knowledge_documents"))


def current_profile():
    return storage.get_profile(NUTRITION_PATH, session.get("profile_id", ""))


@app.context_processor
def shared_context():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {"csrf_token": session["csrf_token"], "active_profile": current_profile()}


@app.before_request
def protect_local_writes():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not expected or not secrets.compare_digest(supplied, expected):
            if request.path.startswith("/api/"):
                return jsonify(error="Page session expired. Refresh the page and try again."), 403
            abort(403, description="Page session expired. Refresh and try again.")
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != request.host:
            abort(403)


def api_errors(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except requests.exceptions.JSONDecodeError:
            return jsonify(error="Ollama returned invalid JSON."), 502
        except requests.HTTPError:
            return (
                jsonify(
                    error="Ollama rejected the request. Check that gemma3:1b and nomic-embed-text are installed."
                ),
                502,
            )
        except requests.RequestException:
            return (
                jsonify(
                    error="Could not reach Ollama. Start Ollama and check both required models."
                ),
                502,
            )
        except food_images.AnalysisUnavailable as error:
            return jsonify(error=str(error)), 503
        except nutrition.ModelResponseError as error:
            return jsonify(error=str(error)), 502
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except sqlite3.Error:
            app.logger.exception("Local database error")
            return (
                jsonify(
                    error="The local database could not be read or saved. Check disk space and permissions."
                ),
                500,
            )

    return wrapped


def question_passages(question):
    connection = db_connect()
    try:
        count = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    finally:
        connection.close()
    return [dict(row) for row in retrieve_passages(question)] if count else []


def validate_question(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError("Enter a question of 1–2,000 characters.")
    return value.strip()


@app.get("/documents")
def documents():
    profile = current_profile()
    try:
        photos = food_images.gallery(NUTRITION_PATH, profile["id"]) if profile else []
        return render_template("food_collection.html", photos=photos)
    except (sqlite3.Error, OSError):
        app.logger.exception("Food photo collection storage unavailable")
        return (
            render_template(
                "food_collection.html",
                photos=[],
                collection_error="Food photo storage is unavailable. Check free disk space and folder permissions, then reload.",
            ),
            503,
        )


@app.post("/api/images/analyze")
@api_errors
def analyze_image():
    profile = current_profile()
    if not profile:
        return jsonify(error="Save your profile before analyzing food photos."), 409
    upload = request.files.get("image")
    if not upload:
        return jsonify(error="Choose a food or label photo."), 400
    image = food_images.prepare_image(upload)
    result = food_images.analyze(
        image, request.form.get("kind", "meal"), request.form.get("food", ""), DATA_DIR
    )
    return jsonify(analysis=food_images.create_draft(NUTRITION_PATH, profile["id"], image, result))


@app.get("/api/images/draft/<draft_id>")
def preview_image(draft_id):
    profile = current_profile()
    image = food_images.draft_image(NUTRITION_PATH, profile["id"], draft_id) if profile else None
    if image is None:
        abort(404)
    response = send_file(io.BytesIO(image), mimetype="image/jpeg")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.delete("/api/images/draft/<draft_id>")
@api_errors
def discard_image(draft_id):
    profile = current_profile()
    if not profile:
        return jsonify(error="Profile not found."), 409
    with storage.connect(NUTRITION_PATH) as db:
        food_images.init_tables(db)
        db.execute(
            "DELETE FROM image_drafts WHERE id=? AND profile_id=?", (draft_id, profile["id"])
        )
    return jsonify(discarded=True)


@app.post("/api/images/confirm/<draft_id>")
@api_errors
def confirm_image(draft_id):
    profile = current_profile()
    if not profile:
        return jsonify(error="Save your profile first."), 409
    return jsonify(
        food_images.confirm(NUTRITION_PATH, profile, draft_id, request.get_json(silent=True))
    )


@app.get("/food-photos/<int:entry_id>")
def consumed_photo(entry_id):
    profile = current_profile()
    image = food_images.photo(NUTRITION_PATH, profile["id"], entry_id) if profile else None
    if image is None:
        abort(404)
    response = send_file(io.BytesIO(image), mimetype="image/jpeg")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/profile")
def profile_page():
    return render_template(
        "profile.html",
        age_ranges=storage.AGE_RANGES,
        goals=storage.GOALS,
        activities=storage.ACTIVITIES,
    )


@app.route("/api/profile", methods=["GET", "PUT", "POST", "DELETE"])
@api_errors
def profile_api():
    if request.method == "GET":
        return jsonify(profile=current_profile())
    if request.method == "DELETE":
        with storage.connect(NUTRITION_PATH) as db:
            profile_id = session.get("profile_id", "")
            db.execute("DELETE FROM comparisons WHERE profile_id=?", (profile_id,))
            calories.init_tables(db)
            food_images.init_tables(db)
            for table in (
                "food_photos",
                "image_drafts",
                "calorie_entries",
                "calorie_days",
                "calorie_settings",
            ):
                db.execute(f"DELETE FROM {table} WHERE profile_id=?", (profile_id,))
            db.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
        session.pop("profile_id", None)
        return jsonify(deleted=True)
    data = request.get_json(silent=True)
    profile_id = session.get("profile_id") or secrets.token_urlsafe(24)
    profile = storage.save_profile(NUTRITION_PATH, profile_id, data)
    session["profile_id"] = profile_id
    calories.sync_profile_target(NUTRITION_PATH, profile)
    return jsonify(profile=profile)


@app.get("/evaluation")
def evaluation_page():
    day = request.args.get("date", calories.today())
    try:
        day = calories.valid_date(day)
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("evaluation_page"))
    profile = current_profile()
    tracking = calories.snapshot(NUTRITION_PATH, profile["id"], day) if profile else None
    return render_template(
        "evaluation.html", tracking=tracking, selected_date=day, today=calories.today()
    )


@app.route("/api/calories", methods=["GET", "PUT"])
@api_errors
def calorie_day_api():
    profile = current_profile()
    if not profile:
        return jsonify(error="Save your profile before tracking calories."), 409
    if request.method == "GET":
        day = calories.valid_date(request.args.get("date", calories.today()))
        return jsonify(calories.snapshot(NUTRITION_PATH, profile["id"], day))
    data = request.get_json(silent=True)
    if isinstance(data, dict) and "target" in data:
        return (
            jsonify(
                error="Daily targets are calculated from Your profile. Update your measurements there."
            ),
            400,
        )
    if profile.get("daily_target") is None:
        return jsonify(error="Complete the energy estimate in Your profile first."), 409
    return jsonify(calories.save_day(NUTRITION_PATH, profile["id"], data))


@app.post("/api/calories/entries")
@api_errors
def calorie_entry_api():
    profile = current_profile()
    if not profile:
        return jsonify(error="Save your profile before tracking calories."), 409
    return jsonify(calories.add_entry(NUTRITION_PATH, profile["id"], request.get_json(silent=True)))


@app.delete("/api/calories/entries/<int:entry_id>")
@api_errors
def calorie_delete_api(entry_id):
    profile = current_profile()
    if not profile:
        return jsonify(error="Save your profile before tracking calories."), 409
    result = calories.delete_entry(NUTRITION_PATH, profile["id"], entry_id)
    if result is None:
        return jsonify(error="Food entry not found."), 404
    return jsonify(result)


@app.get("/api/evaluations/export")
def export_evaluations():
    response = jsonify(
        comparisons=storage.comparisons(NUTRITION_PATH, session.get("profile_id", ""))
    )
    response.headers["Content-Disposition"] = (
        'attachment; filename="triple-trouble-evaluations.json"'
    )
    return response


@app.get("/api/health")
def health():
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=3)
        response.raise_for_status()
        models = response.json().get("models", [])
        names = {m.get("name", "") for m in models if isinstance(m, dict)}
        ready = {
            model: model in names or model + ":latest" in names
            for model in (MODEL, EMBEDDING_MODEL)
        }
        return jsonify(
            ollama=True,
            models=ready,
            ready=all(ready.values()),
            vision_model=food_images.VISION_MODEL,
            vision_ready=(
                importlib.util.find_spec("Vision") is not None
                if food_images.VISION_MODEL == "apple-vision"
                else food_images.VISION_MODEL in names
                or food_images.VISION_MODEL + ":latest" in names
            ),
        )
    except (requests.RequestException, ValueError, AttributeError):
        return jsonify(ollama=False, models={}, ready=False)


@app.post("/documents/reindex/<path:filename>")
def reindex_document(filename):
    if (
        Path(filename).name != filename
        or "/" in filename
        or "\\" in filename
        or not filename.lower().endswith(".pdf")
    ):
        abort(404)
    path = UPLOAD_FOLDER / filename
    if not path.is_file():
        abort(404)
    count = index_pdf(path)
    flash(
        f"Index attempt finished: {count} chunks. Check the status below.",
        "success" if count else "error",
    )
    return redirect(url_for("knowledge_documents"))


@app.post("/api/chat")
@api_errors
def chat():
    payload = request.get_json(silent=True)
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list) or not 1 <= len(messages) <= 40:
        return (
            jsonify(
                error="Send between 1 and 40 conversation messages. Clear chat to start again."
            ),
            400,
        )
    safe_messages = []
    for message in messages:
        if not isinstance(message, dict):
            return jsonify(error="Each message must have a role and content."), 400
        role, content = message.get("role"), message.get("content")
        if (
            role not in ("user", "assistant")
            or not isinstance(content, str)
            or not content.strip()
            or len(content) > 12000
        ):
            return (
                jsonify(
                    error="Messages must have user/assistant roles and 1–12,000 text characters."
                ),
                400,
            )
        safe_messages.append({"role": role, "content": content})
    if safe_messages[-1]["role"] != "user":
        return jsonify(error="The last message must be a user question."), 400
    question = validate_question(safe_messages[-1]["content"])
    mode = payload.get("mode", "general")
    if mode not in ("general", "personalized"):
        return jsonify(error="Choose general or personalized mode."), 400
    profile = current_profile() if mode == "personalized" else None
    if mode == "personalized" and not profile:
        return jsonify(error="Save your profile first, or choose general mode."), 409
    if re.search(
        r"\b(what|which)\b.*\b(papers?|documents?|files?)\b.*\b(collection|uploaded|have|available)\b|\b(papers?|documents?)\s+(in|inside)\s+(my|the)\s+(document\s+)?collection\b",
        question,
        re.I,
    ):
        with db_connect() as db:
            filenames = [
                row["filename"]
                for row in db.execute(
                    "SELECT filename FROM documents WHERE status='indexed' ORDER BY filename"
                )
            ]
        answer = (
            "Indexed PDF papers: " + ", ".join(filenames)
            if filenames
            else "There are no indexed PDF papers in the document collection."
        )
        return jsonify(
            message={"role": "assistant", "content": answer, "sources": [], "mode": mode}
        )
    return jsonify(
        message=nutrition.generate(
            OLLAMA_CHAT_URL, MODEL, safe_messages, question_passages(question), profile
        )
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
