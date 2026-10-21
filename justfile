# pccontext development tasks. Run `just` to list them.

pythons := "3.11 3.12 3.13 3.14"

default:
    @just --list

# Install the project and all development groups
sync:
    uv sync --all-groups

# Run the tests on the default Python
test *args:
    uv run pytest {{args}}

# Run the tests on every supported Python, each in its own environment
test-all *args:
    #!/usr/bin/env bash
    set -uo pipefail
    failed=()
    for py in {{pythons}}; do
        echo "==> Python $py"
        UV_PROJECT_ENVIRONMENT=.venvs/py$py uv run --python "$py" pytest -q {{args}} || failed+=("$py")
    done
    if [ ${#failed[@]} -gt 0 ]; then echo "Failed on: ${failed[*]}"; exit 1; fi

# Run the tests with a coverage report
cov:
    uv run pytest -n 4 --cov pccontext --cov-report=term-missing

# Run the live Ogmios tests (OGMIOS_URL, default ws://localhost:1337)
test-live url="ws://localhost:1337":
    PCCONTEXT_OGMIOS_URL={{url}} uv run pytest tests/backend/test_ogmios_live.py

# Lint, check formatting and type-check
qa: lint typecheck

lint:
    uv run ruff check .
    uv run ruff format --check .

# Apply lint fixes and format the code
format:
    uv run ruff check --fix .
    uv run ruff format .

typecheck:
    uv run ty check

# Build the documentation; warnings are errors
docs:
    uv run --group docs sphinx-build -W --keep-going -b html docs/source docs/build/html

# Build the sdist and wheel
build:
    uv build

# Update the changelog from the commit history
changelog:
    uv run cz ch

# Cut a version and changelog from the commits, then push with `git push --follow-tags`
bump:
    uv run cz bump

# Reinstall cbor2 as the pure Python implementation (see ensure_pure_cbor2.sh)
ensure-pure-cbor2:
    ./ensure_pure_cbor2.sh

# Remove build, test and cache artifacts
clean:
    rm -rf build dist .eggs cov_html docs/build .pytest_cache .ruff_cache .coverage
    find . -name '__pycache__' -not -path './.venv/*' -exec rm -rf {} +
