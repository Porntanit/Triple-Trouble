# สำหรับเพื่อนที่ได้รับ ZIP

เริ่มจาก **START-HERE-TH.md** แล้วเปิด **Start-on-Mac.command** ตัวเปิดจะเตรียมแพ็กเกจและเปิดเว็บให้บน Mac

# Triple-Trouble · Personalized Nutrition

A local Flask nutrition chat and photo-based food diary for the BAScii Generative AI project by **Triple-Trouble**: Porntanit Suramonsikan (Fahsai), Ingboon Lersvidhaya (Ing), and Phichayapa Loymek (Peach).

## Run on a Mac

Use **Python 3.10** (or a newer compatible Python), macOS, and [Ollama](https://ollama.com/). Open Terminal in this repository:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Open the Ollama app and download the two existing models if needed:

```bash
ollama pull gemma3:1b
ollama pull nomic-embed-text
python app.py
```

Open <http://127.0.0.1:5000>. If that port is occupied, use `PORT=5055 python app.py` and <http://127.0.0.1:5055>.

Normal operation uses local Ollama and Apple's local Vision framework via PyObjC. No paid API, cloud image upload, CDN or analytics. Installation/model downloads need internet. The default photo classifier and OCR require macOS; text chat and the source library can run elsewhere. The server binds only to `127.0.0.1`, with debugging off.

## Use the connected flow

1. **Your profile:** save a nickname, exact adult age, goal, activity, budget, meals/day, height in cm, weight in kg and an energy equation. Preferences/restrictions remain available for chat. Previously saved profiles keep their data and are prompted for the new measurements.
2. The server calculates an **estimated maintenance energy target**, not a strict upper limit or a weight-loss prescription. It uses [Mifflin–St Jeor](https://pubmed.ncbi.nlm.nih.gov/2305711/) resting energy multiplied by an activity factor (1.2, 1.375, 1.55 or 1.725; [factor reference](https://www.hhs.texas.gov/sites/default/files/documents/common-comparative-standards-for-rds-ltc-settings.pdf)). The published formula requires the female or male coefficient; the app never infers it. No automatic deficit is applied based on goals. Not intended for pregnancy, breastfeeding or medical nutrition needs.
3. **Nutrition chat:** ask food/nutrition questions with optional profile context. The original `gemma3:1b` text chat, browser history, PDF retrieval and citations remain. Scanning a photo is available on this page too.
4. **Scan food:** choose Meal photo or Nutrition label and upload JPG, PNG or WebP (up to 8 MB, 30 megapixels). Food name is optional. EXIF metadata is stripped, and the image is resized to at most 1600px. macOS Vision identifies likely food categories or reads label text. Gemma produces a serving estimate or nutrition observations.
5. **Review:** inspect the recognized food, calorie estimate, assumed serving and uncertainty. Label energy is accepted only from explicitly read `Calories`/`kcal`; multiple conflicting readings require correction. English nutrition panels are the tested OCR path. Thai-only panels and handwriting may not be read reliably. Choose whether the value is per serving, per 100g or per assumed meal serving, then enter portions/servings or grams eaten. Name and kcal are prefilled where recognized and remain editable.
6. **Confirm:** select **I ate this — add to tracker**. Only this action saves the food to the diary and its photo to Document collection. Merely scanning, asking a question or discarding a preview does not record consumption. Double-click/retry protection prevents duplicate meals. The confirmation button is the consumption shortcut; a conversational “I ate this” text message does not silently log food.
7. **Calorie tracker:** the three cards show daily consumed kcal, remaining kcal and a clickable 1–5 self-rating. The target comes from the profile; there is no manual target form. New profile measurements update today's target and the default for future dates, while past days retain target snapshots. Select earlier Bangkok dates to review/backfill. History grows as dates are logged. Remove an incorrect food entry to remove its associated photo too.
8. **Document collection:** displays only your confirmed food photos with their date, name and logged calories. Temporary scan previews expire after one hour and are cleaned during subsequent image operations. Photos and logs belong to the current browser's profile.

**Compare answers and its evaluation UI/routes have been removed** as requested. Existing historical comparison records are not deleted; the session-scoped legacy JSON export remains at `/api/evaluations/export` for data retention.

## Nutrition PDF sources

Reference files remain separate from food photos. Open **Nutrition PDF sources** at the bottom of Document collection, or `/knowledge`, to use the preserved PDF/TXT/DOCX/MD upload interface. Text PDFs are chunked and embedded by `nomic-embed-text` in the original local index. TXT/DOCX/MD are stored only. Uploads are at most 16 MB including request overhead. Scanned PDFs need external OCR. Start Ollama then choose **Reindex** to retry failed indexing.

Chat retrieves up to five passages using cosine similarity with a 0.25 heuristic cutoff. Recognized `[filename, page N]` references are checked against retrieved passages; unknown bracketed references are removed. **Valid filenames/pages do not prove claim support.** Check the PDF/excerpt yourself. A small model can still invent prose, nutritional numbers or other references.

## Accuracy and limits

- Photo classification recognizes food categories, **not food weight, hidden oils, recipe ingredients or exact nutrition**. The calorie value is a language-model estimate for an explicitly stated assumed serving. It is not a measurement of the photographed plate. Similar-looking dishes can differ substantially.
- A label's OCR energy reading is more directly grounded, but blurry text, multiple columns, serving units, kJ vs kcal and package portion counts can still cause mistakes. Review the text and serving basis before confirming. Missing or ambiguous energy is left blank rather than replaced with a fabricated value.
- Nutrition observations are generated suggestions, not a validated healthy/unhealthy score. Neither images nor the app can guarantee allergy safety or clinical suitability.
- The energy formula is an adult estimate. It is calculated deterministically; Gemma does not set the daily target. Existing profiles without measurements are asked to complete them before confirming image meals.
- Inference is synchronous: allow up to a few minutes on the first scan. Each AI request has a 180-second timeout. Use a small local source collection, not a multi-user production workload.
- HEIC is not supported; export it as JPG first. No barcode or portion-scale measurement is implemented.

## Local data

Excluded from Git: `uploads/`, `document_index.sqlite3`, `nutrition.sqlite3`, `.session-key`, `.venv/` and SQLite sidecars.

`nutrition.sqlite3` stores structured profiles, daily target snapshots, food entries, self-ratings, confirmed photo BLOBs, analysis provenance and temporary drafts. `document_index.sqlite3` stores the original source-document index. Browser storage holds chat histories. `.session-key` is a persistent random cookie-signing key created with private permissions. Files are local but not encrypted.

There is no login/profile picker: a signed browser session selects the profile. Use the same hostname/browser, and don't share it with untrusted people. Clearing cookies loses the profile selection. **Delete profile & history** removes its profile, calorie records, photos and drafts, plus legacy comparisons; shared reference PDFs remain.

Environment variables:

- `PORT`: default 5000.
- `TT_DATA_DIR`: optional data directory, default repository root (preserves original paths).
- `FLASK_SECRET_KEY`: optional override for the saved signing key.
- `OLLAMA_VISION_MODEL`: default `apple-vision`; advanced users may instead install and select an Ollama vision model. The default needs no extra vision model download. Text generation remains `gemma3:1b`.

Writes require CSRF protection. API clients first GET a page, preserve its session cookie and pass the page's meta `csrf-token` as `X-CSRF-Token`. Image uploads use multipart `image`, `kind` and optional `food`; explicit confirmation is a separate write.

## Checks

```bash
python -m unittest discover -s tests -v
python -m pip install -r requirements-dev.txt
python -m black --check app.py storage.py calories.py energy.py nutrition.py food_images.py tests
```

Deterministic tests mock model/OCR results. See [verification](docs/VERIFICATION.md) for separately recorded live checks and limitations, and [changed files](docs/CHANGES.md) for implementation details.
