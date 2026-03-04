# Contributing to Agent Hub Linux

Thanks for helping improve Agent Hub Linux! This guide keeps contributions fast and consistent.

## Before you start

- Search existing issues/PRs to avoid duplicates.
- If you plan a large change, open an issue first to align on approach.

## Development setup

1. Fork the repo and create a branch from `main`.
2. Install dependencies: `make install`
3. Generate types: `make typegen`
4. Run in dev mode: `make dev`

## Development workflow

1. Make focused, incremental commits.
2. Run `make lint` and `make typecheck` before submitting.
3. Run `make test` to verify nothing is broken.
4. Update docs or comments when behavior changes.

## Pull requests

- Keep PRs small and scoped to one change.
- Include a clear description, screenshots for UI changes, and steps to verify.
- Note any follow-up work or known limitations.

## Code style

- **Python:** Ruff for linting and formatting, Pyright in strict mode.
- **TypeScript:** Standard tsc with strict checks.
- Keep backend models and frontend types in sync via `make typegen`.

## Questions

If you're unsure about direction or scope, open an issue and ask.
