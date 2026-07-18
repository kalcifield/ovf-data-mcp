# Repository Guidelines

## Project Structure & Module Organization

Python code uses the `src` layout under `src/vizugy/`. Keep stable domain models in
`models.py`, intent-level workflows in `service.py`, and upstream details in
`providers.py` (ArcGIS) or `vra_provider.py` (VRAQuery). `cli.py` and `mcp_server.py`
must remain thin adapters over the same service methods. Tests live in `tests/` and
follow the corresponding capability, for example `test_vra_provider.py` and
`test_investigation.py`. Design findings and verified upstream behavior belong in
`docs/`. See `README.md` for the public interface.

## Build, Test, and Development Commands

Use Python 3.11+ and `uv`:

```bash
uv sync --extra test              # install runtime and development dependencies
uv run vizugy --help              # inspect or run the CLI
uv run ovf-data-mcp               # start the stdio MCP server
uv run pytest -q                  # run deterministic tests and MCP smoke tests
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
```

Run `uv run pre-commit run --all-files` before submitting broad changes.

## Coding Style & Naming Conventions

Use four-space indentation, Python type annotations, and Ruff formatting. Modules,
functions, and variables use `snake_case`; classes and Pydantic models use
`PascalCase`. Prefer small typed domain objects over leaking upstream Hungarian field
names. Preserve raw provider semantics inside adapters. CLI/MCP outputs must keep data
on stdout and diagnostics on stderr.

## Testing Guidelines

Tests use `pytest`, `pytest-asyncio`, `httpx.MockTransport`, and recorded deterministic
responses. Name tests `test_<behavior>`. Cover normalization, bounds, ambiguity,
upstream errors, compact output, and CLI/MCP parity. Routine tests must not require live
OVF services; use small live probes only for explicit contract validation. No numeric
coverage threshold is currently enforced.

## Commit & Pull Request Guidelines

Follow the existing Conventional Commit style: `feat:`, `fix:`, `docs:`, `test:`, or
`chore:`. Keep commits scoped and avoid mixing generated or unrelated files. Pull
requests should state the user-facing behavior, upstream assumptions, validation
commands, and live probes performed. Link relevant issues and include example JSON or
CLI calls when schemas change; screenshots are generally unnecessary.

## Security, Data, and Upstream Etiquette

Never commit tokens or credentials. Keep queries bounded, reuse metadata/token caches,
and avoid crawling or load-testing OVF endpoints. Treat operational readings as
potentially unchecked, preserve provenance, label inferred semantics, and keep anomaly
interpretation outside the tool.
