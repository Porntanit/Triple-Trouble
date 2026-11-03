# Local Ollama Chat

A minimal Flask chat interface for the locally running Ollama model `gemma3:1b`. Conversation history is saved in your browser's local storage and sent to Flask with each request. Flask contacts Ollama, so the browser never calls the Ollama API directly.

## Requirements

- Python 3.9 or newer
- [Ollama](https://ollama.com/) installed and running locally
- The `gemma3:1b` model downloaded
- The `nomic-embed-text` model downloaded (used only to create/search document embeddings)

Prepare the model if needed:

```bash
ollama pull gemma3:1b
ollama pull nomic-embed-text
```

## Setup and run

From this directory, create and activate a virtual environment, install dependencies, and start Flask:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000> in your browser. The app listens on `127.0.0.1` only. Ollama must be available at `http://localhost:11434`.

## Use

Type a message and press Enter or select the send button. Use Shift+Enter for a new line. Select **Clear chat** to remove the saved conversation from this browser. Replies use non-streaming Ollama responses.

## Document collection

Select **Document collection** in the navigation to manage local documents. Choose a PDF, TXT, DOCX, or Markdown (`.md`) file and select **Upload**. Files are stored in `uploads/`; PDF text is extracted by PyMuPDF, split into overlapping passages, and embedded by Ollama's `nomic-embed-text` model. Passage text, filename, page number, and vector are stored in `document_index.sqlite3`. The page shows each PDF's indexing state and chunk count. TXT, DOCX, and Markdown remain uploadable but are not indexed for chat. Scanned/image-only PDFs with no extractable text are reported as not indexable; OCR is not performed. Use **Delete** to remove a file and its indexed passages. Uploads are limited to 16 MB per request, and duplicate filenames are not overwritten. Models are never downloaded automatically.

Ask the chat **“What papers are in my document collection?”** to see indexed PDF filenames. For research questions, the app retrieves up to five relevant passages and asks Gemma to cite their exact filename and page. If the index is empty or Ollama cannot provide embeddings, check the indexing status and make sure Ollama is running with `nomic-embed-text` available.

The app creates `uploads/` when the document collection is first opened. Keep this folder local and do not add private uploaded documents to source control.

## Test the pages

1. Start Ollama and ensure the model is available with `ollama pull gemma3:1b` if needed.
2. From the project directory, activate the virtual environment and run `python app.py` as shown above.
3. Open <http://127.0.0.1:5000>. Send a chat message and confirm the assistant replies. If its response contains a URL, confirm it is clickable and opens in a new tab. Refresh to confirm conversation history remains.
4. Make sure `nomic-embed-text` is available with `ollama list` (download it manually with `ollama pull nomic-embed-text` if needed). Upload a text-based PDF and confirm the success message and chunk count. An image-only PDF should report no extractable text.
5. Ask “What papers are in my document collection?” and confirm the uploaded PDF filename is returned. Ask a question whose answer appears in the PDF and confirm the response cites the filename and page number. Ask an unrelated question and confirm the assistant does not make up a citation.
6. Refresh the page to confirm the uploaded file and chunk count remain. Upload a disallowed file such as `.png` and confirm an error message. Try uploading a file larger than 16 MB to confirm the size limit message.
7. Select **Delete** beside the uploaded file and confirm the success message and that it disappears from the list. Return to **Chat** and confirm the chat page still loads.

Flask listens on `127.0.0.1` only.
