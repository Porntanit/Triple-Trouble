# Repository Guidelines

## Project Structure & Module Organization

This repository is currently empty: it has no source tree, tests, assets, or project metadata yet. As the project takes shape, keep application code in a clearly named directory (such as `src/`), tests in `tests/` or beside the modules they cover, and static assets in `assets/` or `public/`. Add a README and the relevant package/build manifest when choosing the implementation stack. Keep modules focused and avoid committing generated output or local environment files.

## Build, Test, and Development Commands

There are no build, test, or run commands configured yet. When adding a toolchain, document its prerequisites and standard workflows in the README and here. Provide reproducible commands for installing dependencies, running the application, formatting/linting, and executing the full test suite; prefer the repository's package scripts or task runner over undocumented local commands.

## Coding Style & Naming Conventions

No formatter or language convention is established yet. Follow the conventions of the selected language and add formatter/linter configuration with the first implementation. Use descriptive, consistent names: modules and files should reflect their responsibility, public APIs should use clear domain terms, and tests should identify the behavior they cover. Keep changes small and format files with the configured tool before review.

## Testing Guidelines

No testing framework or coverage requirement is configured. Add automated tests alongside new behavior and regression fixes, using the chosen framework's standard discovery and naming patterns (for example, `test_*.py` or `*.test.ts`). Tests should be deterministic and runnable with one documented command. Include any necessary setup instructions, but do not commit secrets or machine-specific test data.

## Commit & Pull Request Guidelines

No Git history is available to establish a commit-message convention. Use concise imperative commit subjects (for example, `Add request validation`) until the project adopts a documented convention. Pull requests should explain the change and its motivation, note how it was verified, link related issues when applicable, and include screenshots for user-visible changes.

## Security & Configuration

Keep credentials and personal configuration out of source control. Provide safe example configuration with placeholder values and document required environment variables when the application introduces them.
