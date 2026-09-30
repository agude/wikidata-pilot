# Task runner for wikidata_pilot. See the project-standards skill for the verb
# contract: lint is read-only and total, format is its mutating twin, and
# check is the full gate that CI runs.

# Default: list available recipes
set positional-arguments

default:
    @just --list

# Run the CLI with the repository project and cache configuration.
pilot *args:
    @./bin/pilot "$@"

# Use writable repository-local uv and library caches unless overridden.
export UV_CACHE_DIR := env_var_or_default("UV_CACHE_DIR", justfile_directory() / ".uv-cache")
export UV_PYTHON_INSTALL_DIR := env_var_or_default("UV_PYTHON_INSTALL_DIR", justfile_directory() / ".uv-python")
export PYSTOW_HOME := env_var_or_default("PYSTOW_HOME", justfile_directory() / ".pystow")
export WIKIDATA_PILOT_STATE_DIR := env_var_or_default("WIKIDATA_PILOT_STATE_DIR", justfile_directory() / ".wikidata-pilot-state")

# Install dependencies
sync:
    uv sync --dev

# All read-only static checks
lint:
    uv run ruff check .
    uv run ruff format --check .
    shellcheck bin/pilot bin/pre-commit.sh

# Apply formatting and safe lint fixes
format:
    uv run ruff format .
    uv run ruff check --fix .

# Type check
# New repos: include tests/. Migrating an existing repo: start with the
# package alone — widening to tests usually surfaces real errors that
# belong in their own change.
type-check:
    uv run mypy src/wikidata_pilot/ tests/

# Run tests
test *args:
    uv run pytest -vv {{ args }}

# Everything CI runs
check: lint type-check test smoke-test

# Verify the installed console script from a built package.
smoke-test:
    uv build --clear
    uv run --no-project --isolated --with ./dist/*.whl wikidata-pilot --help

# Build the package
build:
    uv build

# GitHub release tags must match the package's single version source.
verify-release:
    uv run python -c 'import os; from wikidata_pilot import __version__; expected = "v" + __version__; actual = os.environ.get("GITHUB_REF_NAME"); assert actual == expected, f"Expected tag {expected}, got {actual}"'

# Remove build and cache artifacts
clean:
    rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache .mypy_cache

# Install the pre-commit hook into this clone
hooks-install:
    @mkdir -p .git/hooks
    @cp bin/pre-commit.sh .git/hooks/pre-commit
    @chmod +x .git/hooks/pre-commit
    @echo "Pre-commit hook installed."
