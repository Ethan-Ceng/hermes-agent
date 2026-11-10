"""Dependency checker contracts on independent miniature packages."""

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture
def checker():
    source = Path(__file__).resolve().parents[2] / "scripts" / "hermes_db_boundary_lint.py"
    spec = importlib.util.spec_from_file_location("hermes_db_boundary_checker_contract", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def put(root, path, text=""):
    path = root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_reviewed_symbols_do_not_grant_the_rest_of_a_module(checker, tmp_path):
    put(tmp_path, "gateway/__init__.py")
    put(tmp_path, "gateway/retry_values.py", "LIMIT = 3\nSECRET = object()\n")
    consumer = "hermes_db/domains/cron/postgres/attempts.py"
    put(tmp_path, consumer, "from gateway import retry_values as policy\ndef cap():\n    return policy.LIMIT\n")
    rules = {"reviews": [{"target": "gateway.retry_values.LIMIT", "consumers": [consumer],
                           "category": "shared-pure", "reason": "Existing closed attempt bound"}]}
    _, errors = checker.check(tmp_path, rules)
    assert errors == []
    put(tmp_path, consumer, "from gateway import retry_values as policy\ndef cap():\n    return policy.SECRET\n")
    _, errors = checker.check(tmp_path, rules)
    assert len(errors) == 1 and "gateway.retry_values.SECRET" in errors[0]


@pytest.mark.parametrize("consumer,target", [
    ("hermes_db/core/units.py", "hermes_db.domains.cron.api"),
    ("hermes_db/core/__init__.py", "hermes_db.domains.cron.api"),
    ("hermes_db/domains/cron/postgres/attempts.py", "gateway.delivery_ledger"),
    ("hermes_db/domains/cron/postgres/attempts.py", "hermes_db.integration"),
    ("hermes_db/infra/backends/postgresql/units.py", "hermes_db.integration.compose"),
    ("hermes_db/infra/backends/postgresql/units.py", "hermes_db.tables.metadata"),
    ("hermes_db/infra/backends/postgresql/units.py", "hermes_db.core.catalog"),
    ("hermes_db/infra/backends/postgresql/units.py", "hermes_db.domains.sessions.store"),
    ("hermes_db/infra/backends/postgresql/units.py", "hermes_cli.db_setup"),
    ("hermes_db/domains/cron/postgres/attempts.py", "hermes_db.integration.compose"),
])
def test_review_cannot_override_dependency_direction(checker, tmp_path, consumer, target):
    put(tmp_path, target.replace(".", "/") + ".py")
    put(tmp_path, consumer, f"import {target} as implementation\nvalue = implementation\n")
    rules = {"reviews": [{"target": target, "consumers": [consumer],
                           "category": "entry-bridge", "reason": "Cannot waive direction"}]}
    _, errors = checker.check(tmp_path, rules)
    assert errors and all("cannot" in error for error in errors)
