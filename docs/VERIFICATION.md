# Verification · 17 November 2026

## Automated checks

15 standard-library integration tests passed using Flask 3.1.3, requests 2.32.5 and PyMuPDF 1.26.5. Tests run against isolated temporary data, not the preview profile or real project uploads.

Covered:

- All five pages render; empty evaluation state is honest.
- Profile create/retrieve/update, SQLite persistence and browser-session isolation.
- Profile types, enum values, bounds, NaN and CSRF/origin validation.
- Chat message roles, limits and personalized mode without a saved profile.
- General generation excludes the saved profile; no-evidence warnings and fake citation removal.
- Connection errors, timeout and malformed model response handling.
- Real in-memory PDF extraction, indexing with mocked embeddings, retrieval, page citations, file download, duplicate rejection and deletion of chunks/files.
- Blank/scanned-style and corrupt PDFs, disallowed extensions and path traversal.
- Failed index recovery using Reindex; listing indexed PDFs without generation.
- Oversized request rejection using declared request size, without allocating a large test file.
- Changed embedding dimension handling and invalid embedding rejection.
- Comparison uses one retrieval and identical passage/model/settings inputs; only the personalized run receives profile data.
- Ratings, actual dashboard averages, saved profile snapshots and JSON export.
- Cross-profile rating access rejection and profile/evaluation deletion.
- First or second generation failure leaves no partial saved comparison.
- Model health status with installed/missing/offline models (mocked).

## Browser checks

Ran the real Flask server on `127.0.0.1:5055` with disposable data under `/private/tmp/tt-preview`.

- Opened the chat and profile pages in the in-app browser.
- Saved a fictional “Demo student” profile through the actual form and verified it was present after reload.
- Returned to chat and verified Personalized was selected with the saved profile visible in navigation.
- Submitted a question with Ollama offline; the real page displayed “Could not reach Ollama. Start Ollama and check both required models.” and restored the send control.
- Checked captured browser error/warning logs: none.
- Saved `chat-preview.jpg` from the actual browser page. No generated answers or evaluation results are presented as actual model results.

## Verification limits

The available Python interpreter was **3.9.6**, not 3.10. All implemented code and the tests ran successfully under 3.9, and formatting targets Python 3.10. An exact Python 3.10 run was **not completed**: downloading the testing tool first timed out, then hit the host's low disk-space limit. Python 3.10 compatibility is intended, but is not claimed as directly runtime-verified. The old system interpreter also emitted a LibreSSL/urllib3 warning; use a modern Python installation for normal use.

Ollama was not installed/on PATH and no service answered at port 11434. **No real Gemma generation, nomic embedding, answer-quality assessment or end-to-end live-model timing was verified.** Tests explicitly mock model output; the browser offline error was checked against the actual environment. User nutrition PDFs were not supplied. Live model checks below remain necessary.

The suite briefly encountered disk-space errors while attempting a large upload fixture. That test was changed to exercise the real 16 MB request-size boundary using request metadata, avoiding unnecessary disk use. The subsequent full 15-test run passed.

## Live-model acceptance checks on your Mac

1. Confirm adequate disk space, Python 3.10 and both models in `ollama list`; start Ollama and Flask.
2. Save a realistic adult profile. Upload a permitted text-based nutrition PDF and confirm a positive indexed chunk count. If needed, select Reindex after the embedding model is ready.
3. Ask a question answered on a known PDF page. Open its citation and verify that the cited sentence actually supports the claim.
4. Ask an unrelated question and check the disclosure and absence of invented evidence. A similarity cutoff cannot guarantee this; record any model failure.
5. Ask the same question in Compare, verify both answers use the same retrieved excerpts and inspect how the personalized answer applies the saved preferences, budget and restrictions.
6. Rate both answers using the passages, export results, restart Flask and revisit the same browser/hostname to verify persistence.
7. Change the profile, repeat, and test a meal-plan request. Check ingredients yourself; do not treat the generated plan as allergy-safe.

## Follow-up: document page disk-space failure

The preview server recorded two `/documents` HTTP 500 errors when creating its uploads directory failed with `OSError: [Errno 28] No space left on device`. The empty document page now avoids creating that directory on GET; upload still creates it when needed. Storage failures on the collection page show an actionable message and disable upload instead of presenting an empty list as if no files existed. Added two regression tests; all **17 tests pass**. Restarted the preview and verified the real Document collection page opens successfully in the browser. Screenshot: `documents-fixed.jpg`.

## Follow-up: profile save feedback

Server logs showed successful profile PUTs followed immediately by reloads, which erased the brief Saved message. Saving now keeps the form open, displays a persistent success banner and Saved button, updates the sidebar without reload, and offers a link to personalized chat. Invalid fields show an explicit message; failures keep the form data for retry. Browser-tested saving the existing fictional Demo student profile, an empty-name validation failure, then restoring and saving the original name. All 17 backend tests still pass. Screenshot: `profile-save-fixed.jpg`.

## Follow-up: live Ollama connection

Located the existing `/Applications/Ollama.app` and local `gemma3:1b` model; Ollama was initially not listening. Opened the installed app and verified its service on port 11434. A direct model smoke request and an actual Flask `/api/chat` request both returned successfully (HTTP 200). Also tested Personalized chat in the browser with the fictional Demo student profile; a real answer appeared and the send control was restored. This supersedes the earlier offline-only connection verification limit, but does not establish answer quality. In fact the small model still invented an evidence-style statement without documents and ignored a request to avoid calorie estimates; the UI showed missing-evidence warnings and removed an invalid reference. Nutritional accuracy and evidence entailment remain unverified.

Started downloading `nomic-embed-text` (274 MB) with the installed Ollama CLI. It was still downloading at the time of this update; live PDF embedding has NOT yet been verified. The status display now distinguishes chat readiness from missing PDF search models and refreshes every 30 seconds. Do not interpret a working chat as a verified PDF retrieval test. Screenshot: `ollama-chat-connected.jpg`.

## Daily calorie tracker verification

All **19 integration tests passed** after replacing the main Evaluation page with the calorie tracker. Added coverage for manually set targets, multiple food entries and totals, negative remaining values, daily ratings, preserving previous days' target snapshots, new-day defaults/reset totals, invalid/future dates, invalid numbers, cross-profile access and profile-deletion cleanup. The existing comparison evaluation tests now run against `/answer-evaluation`.

Browser-tested the existing fictional Demo student profile: set a demonstration target of 2,000 kcal, added a Demo lunch entry of 650 kcal, verified 1,350 kcal remaining, clicked a 4/5 rating, and reloaded. Both the cards and history row retained the expected values. Checked a narrow view and a 1280px desktop view to verify stacked mobile cards and three horizontal desktop cards, then reset the temporary viewport. `calorie-tracker.jpg` shows test entries, not actual user consumption or a recommended target.

## Connected photo flow and automatic targets (latest)

All **21 current integration tests pass**. The obsolete comparison tests were replaced with explicit 404 checks for removed routes and tests for the requested photo flow. Coverage includes known energy formula arithmetic, invalid measurements, target synchronization and historical snapshots, image validation, draft ownership, no consumption/gallery insertion before confirmation, idempotent confirmation/portion multiplication, photo access isolation, discard/expiry, removal and profile cleanup, label energy parsing and ambiguity, model failure/malformed output, and preserved PDF/chat regressions.

Live checks on this Mac (not mocked):

- Native macOS Vision OCR read the generated English test panel exactly: serving size 1 container (150 g), Calories 230, protein 10 g, fat 8 g, carbohydrate 30 g.
- Native Vision classified a public recipe photo as `food`/`spaghetti`; Gemma produced an editable named serving estimate with an explicit assumed portion. This proves the classification/generation pipeline runs, **not nutritional accuracy**. A live small-model estimate for spaghetti was not independently nutrition-validated.
- Browser: saved adult measurements on the existing fictional Demo student profile; the calculated estimate appeared in the profile and automatically changed the tracker target, retaining previously logged food and self-rating. This demonstration target is not a recommendation for the real user.
- Browser: uploaded the generated test label, observed the prefilled 230 kcal result and unchanged consumed total before confirmation, confirmed it as “Demo label · OCR test”, and saw total consumed increase by 230 with the remaining amount decrease by 230. The confirmed photo appeared in Document collection. Preview notes, original OCR text, editable serving basis and quantity controls were inspected.
- Text chat, PDFs and meal estimates remain local. Apple Vision through PyObjC is the final default, so no extra vision model is required. A Swift-based OCR prototype was discarded after detecting the host's compiler/SDK mismatch. A cancelled optional Moondream download was cleaned up without changing the installed Gemma/embedding models.

Food image test source (used temporarily for classifier testing, not bundled as a project asset): [Nestlé recipe photo](https://www.recetasnestle.com.ve/escuela-sabor/caseras/tips-salsa-pomodoro). The label fixture was generated locally solely for testing. No real user food intake or medical measurements were invented.

Remaining limitations: automatic meal kcal depend on a language-model estimate for a stated assumed portion; no image scale/weight or hidden ingredients can be measured. OCR testing covers a clear English label; Thai-only panels, actual packages, multiple columns and arbitrary recipes require further testing and user review. Exact Python 3.10 runtime validation remains unperformed; this machine's tests run under Python 3.9.6 with Python 3.10-compatible code.

The confirmed-photo collection also has a regression test for disk/storage failure, preserving an actionable recovery message instead of an empty or broken page.
