#!/usr/bin/env python3
"""Enforce hermes_db dependency direction and reviewed, symbol-specific reuse.

The registry is a review document, not an auto-updated baseline. Composition lives
in application owners;all business APIs borrow explicit resources/connections.
Historical migration helpers remain frozen outside runtime dependency grants.
"""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES = Path("scripts/hermes_db_boundary_rules.json")


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    line: int


def module_name(path):
    parts = path.with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def module_exists(root, name):
    path = root.joinpath(*name.split("."))
    return path.with_suffix(".py").is_file() or path.is_dir()


def project_target(root, name):
    first = name.split(".")[0]
    return (root / first).is_dir() or (root / (first + ".py")).is_file()


def _scope_nodes(node):
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from _scope_nodes(child)


class Imports(ast.NodeVisitor):
    def __init__(self, root, path, tree):
        self.root, self.path, self.source = root, path, path.as_posix()
        self.parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        self.scopes, self.edges = [], set()

    def add(self, target, line):
        if not project_target(self.root, target):
            return
        parts = target.split(".")
        for end in range(1, len(parts)):
            if not module_exists(self.root, ".".join(parts[:end + 1])):
                target = ".".join(parts[:end + 1])
                break
        self.edges.add(Edge(self.source, target, line))

    def imported(self, node):
        if isinstance(node, ast.Import):
            return [(a.asname or a.name.split(".")[0], a.name if a.asname else a.name.split(".")[0]) for a in node.names]
        parent = node.module or ""
        if node.level:
            package = self.path.parent.parts
            parent = ".".join((*package[:len(package) - node.level + 1], *([parent] if parent else [])))
        return [(a.asname or a.name, parent + "." + a.name) for a in node.names]

    def scope(self, node):
        bindings = dict(self.scopes[-1]) if self.scopes else {}
        for item in _scope_nodes(node):
            if isinstance(item, (ast.Import, ast.ImportFrom)):
                for alias, target in self.imported(item):
                    bindings[alias] = target
                    if target.startswith("hermes_db.") or not module_exists(self.root, target):
                        self.add(target, item.lineno)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                bindings.pop(arg.arg, None)
        self.scopes.append(bindings)
        self.generic_visit(node)
        self.scopes.pop()

    visit_Module = scope
    visit_FunctionDef = scope
    visit_AsyncFunctionDef = scope
    visit_ClassDef = scope

    def qualified(self, node):
        if isinstance(node, ast.Name):
            return self.scopes[-1].get(node.id)
        if isinstance(node, ast.Attribute):
            value = self.qualified(node.value)
            return value + "." + node.attr if value else None
        return None

    def visit_Attribute(self, node):
        parent = self.parents.get(node)
        if not isinstance(parent, ast.Attribute) or parent.value is not node:
            target = self.qualified(node)
            if target:
                self.add(target, node.lineno)
        self.generic_visit(node)

    def visit_Name(self, node):
        parent = self.parents.get(node)
        if isinstance(node.ctx, ast.Load) and not isinstance(parent, ast.Attribute):
            target = self.qualified(node)
            if target:
                self.add(target, node.lineno)

    def visit_Call(self, node):
        if self.source.startswith("hermes_db/domains/"):
            target = self.qualified(node.func)
            file_methods = {"read_bytes", "write_bytes", "read_text", "write_text", "unlink", "mkdir", "rmdir",
                            "stat", "lstat", "is_file", "is_dir", "iterdir"}
            effect_roots = ("subprocess", "multiprocessing", "socket", "requests", "httpx", "aiohttp",
                            "urllib.request", "shutil", "os.remove", "os.unlink", "os.mkdir", "os.makedirs",
                            "os.rmdir", "os.rename", "os.replace", "os.open", "os.stat", "os.lstat",
                            "sqlite3.connect", "sqlite3.Connection", "psycopg.connect", "asyncpg.connect",
                            "sqlalchemy.create_engine")
            if isinstance(node.func, ast.Name) and node.func.id == "open" and target is None:
                target = "filesystem.open"
            elif isinstance(node.func, ast.Attribute) and node.func.attr in file_methods:
                target = "filesystem." + node.func.attr
            elif not target or not below(target, effect_roots):
                target = None
            if target:
                self.edges.add(Edge(self.source, target, node.lineno))
        self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str) and node.value.startswith("hermes_db."):
            if module_exists(self.root, node.value):
                self.add(node.value, node.lineno)


def collect(root):
    edges = set()
    for path in sorted((root / "hermes_db").rglob("*.py")):
        relative = path.relative_to(root)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(relative))
        visitor = Imports(root, relative, tree)
        visitor.visit(tree)
        edges.update(visitor.edges)
    return sorted(edges, key=lambda e: (e.source, e.target, e.line))


def domain(name):
    parts = name.split(".")
    # domains/resource.py holds shared business resources, not a concrete domain package.
    if name == "hermes_db.domains.resource" or name.startswith("hermes_db.domains.resource."):
        return None
    return parts[2] if parts[:2] == ["hermes_db", "domains"] and len(parts) > 2 else None


def entry(source):
    return source.startswith("hermes_db/domains/") and source.endswith("/api.py")


def below(name, roots):
    return any(name == root.rstrip(".") or name.startswith(root.rstrip(".") + ".") for root in roots)


def direction_error(edge):
    source = module_name(Path(edge.source))
    target = edge.target
    if below(source, ("hermes_db.infra", "hermes_db.errors", "hermes_db.settings", "hermes_db.scope", "hermes_db.factory")) and below(target, (
        "hermes_db.domains", "hermes_db.tables", "hermes_db.core.catalog", "hermes_db.integration",
        "hermes_db.factory", "hermes_db.access", "hermes_db.handle", "hermes_db.contracts",
        "hermes_db.schema", "hermes_db.health", "hermes_db.maintenance",
        "hermes_cli", "gateway", "agent", "cron", "plugins", "hermes_state",
    )):
        return "infrastructure cannot select business persistence or application composition"
    if below(source, ("hermes_db.core", "hermes_db.backends")) and below(target,
        ("hermes_db.domains.", "hermes_db.integration.", "hermes_db.factory", "hermes_db.access")
    ):
        return "infrastructure cannot select a domain or application composition"
    if below(source, ("hermes_db.domains",)) and below(target,
        ("hermes_db.integration.", "hermes_db.factory", "hermes_db.access",
         "hermes_cli.db_sessions", "hermes_cli.db_domains", "hermes_cli.db_scope",
         "hermes_cli.db_setup", "hermes_cli.db_diagnostics", "agent.runtime_domain_store")
    ):
        return "lower domain cannot select application composition"
    native = ("hermes_state.", "hermes_state_runtime.", "hermes_cli.kanban_db", "hermes_cli.projects_db",
              "hermes_cli.observability.shared_metrics.", "gateway.hosted_rooms.", "gateway.delivery_ledger.",
              "gateway.session.", "cron.executions.", "cron.incidents.", "cron.delivery_queue.", "cron.notepad.")
    if below(source, ("hermes_db.domains",)) and (target.startswith(native) or target in {n.rstrip(".") for n in native}):
        return "lower domain cannot borrow a Native application facade"
    if below(source, ("hermes_db.domains",)) and below(target, (
        "filesystem", "subprocess", "multiprocessing", "socket", "requests", "httpx", "aiohttp",
        "urllib.request", "shutil", "os.remove", "os.unlink", "os.mkdir", "os.makedirs", "os.rmdir",
        "os.rename", "os.replace", "os.open", "os.stat", "os.lstat", "sqlite3.connect", "sqlite3.Connection",
        "psycopg.connect", "asyncpg.connect", "sqlalchemy.create_engine",
    )):
        return "business persistence cannot own file/network/process effects or construct drivers"
    if below(target, ("hermes_db.operations", "hermes_db.repositories")):
        return "removed global technical namespace has no runtime owner"
    if target.endswith(".*"):
        return "wildcard imports hide dependency ownership"
    return None


def needs_review(edge):
    source = module_name(Path(edge.source))
    target = edge.target
    lower = below(source, ("hermes_db.infra", "hermes_db.core", "hermes_db.backends", "hermes_db.domains"))
    if not lower:
        return False
    if not target.startswith("hermes_db."):
        return True
    if domain(source) and domain(target) and domain(source) != domain(target):
        return True
    return entry(edge.source) and target.startswith(("hermes_db.integration.", "hermes_db.factory", "hermes_db.access"))


def check(root, rules):
    approved = {(source, row["target"]) for row in rules["reviews"] for source in row["consumers"]
                if row.get("category") and row.get("reason")}
    errors = []
    edges = collect(root)
    for edge in edges:
        error = direction_error(edge)
        if not error and needs_review(edge) and (edge.source, edge.target) not in approved:
            error = "dependency needs a symbol-specific review and ownership reason"
        if error:
            errors.append(f"{edge.source}:{edge.line}: {edge.target}: {error}")
    return edges, errors


def main():
    rules = json.loads((ROOT / RULES).read_text(encoding="utf-8-sig"))
    edges, errors = check(ROOT, rules)
    for error in errors:
        print(error)
    print(f"hermes_db boundaries: {len(edges)} resolved imports, {len(errors)} violations")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
