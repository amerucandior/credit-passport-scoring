# Contributing to Credit Passport Scoring

Thank you for your interest in contributing! This guide explains how to contribute improvements, bug fixes, and documentation updates.

## How to contribute

1. Fork the repository.
2. Create a feature branch from `main`:
   ```bash
git checkout -b feature/my-improvement
```
3. Make your changes.
4. Run tests locally.
5. Open a pull request describing your changes.

## Development workflow

- Use `pyproject.toml` as the primary dependency manifest.
- Keep changes small and focused.
- Write tests for bug fixes and new features.
- Update documentation when behavior or APIs change.

## Testing

Add unit tests for parsing, feature extraction, scoring, and API behavior. If the project gains test infrastructure, follow the existing test conventions.

## Code style

- Keep code clear and readable.
- Prefer small helper functions over long monolithic blocks.
- Document non-obvious business logic.

## Reporting issues

If you find a bug or want to request an enhancement, open an issue describing:

- what you expected to happen
- what actually happened
- steps to reproduce
- any relevant logs or sample data

## Pull request guidelines

- Include a descriptive title and summary.
- Explain why the change is needed.
- Link to any related issues.
- Keep PRs small and incremental when possible.
