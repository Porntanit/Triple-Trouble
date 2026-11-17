# Repository Guidelines

## Project Structure & Module Organization

The local Flask app starts in `app.py`. Keep profile/experiment persistence in `storage.py`, prompt/citation logic in `nutrition.py`, profile energy calculations in `energy.py`, daily logs in `calories.py`, image/OCR and confirmation logic in `food_images.py`, templates in `templates/`, browser code/styles in `static/`, and tests in `tests/`. Preserve the existing document routes and local Ollama models. Never commit uploads, databases, `.session-key`, or `.venv/`.

## Build, Test, and Development Commands

`python3.10 -m venv .venv`, activate it, then `python -m pip install -r requirements.txt`. Run with `python app.py`. Run tests with `python -m unittest discover -s tests -v`. Optional formatting: install `requirements-dev.txt`, then `python -m black --check app.py nutrition.py storage.py calories.py energy.py food_images.py tests`. See README for Ollama model setup and environment variables.

## Coding Style & Naming Conventions

Target Python 3.10 and use Black with the configuration in `pyproject.toml`. Use descriptive names, keep modules focused, and format changed Python files before review.

## Testing Guidelines

Use standard-library unittest integration tests in `tests/test_app.py`. Isolate all data in temporary directories and mock Ollama for deterministic tests. Explicitly distinguish mocked tests from live-model acceptance checks. Test new behavior and regression fixes without committing private files or machine-specific fixtures.

## Commit & Pull Request Guidelines

No Git history is available to establish a commit-message convention. Use concise imperative commit subjects (for example, `Add request validation`) until the project adopts a documented convention. Pull requests should explain the change and its motivation, note how it was verified, link related issues when applicable, and include screenshots for user-visible changes.

## Security & Configuration

Keep credentials and personal configuration out of source control. Provide safe example configuration with placeholder values and document required environment variables when the application introduces them.
