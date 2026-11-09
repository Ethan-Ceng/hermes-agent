"""Freeze the hermes_db packaging baseline without importing application code.

This is an implementation audit, not a pytest source-shape test. Run once at the
planning checkpoint; retain its output as historical evidence during the moves.
"""

import ast
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile


ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}", *args], cwd=ROOT, timeout=120)


def signature(node):
    result = ast.unparse(node.args)
    if node.returns:
        result += " -> " + ast.unparse(node.returns)
    return {"signature": result, "async": isinstance(node, ast.AsyncFunctionDef),
            "decorators": [ast.unparse(item) for item in node.decorator_list]}


def definitions(tree):
    result = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            result[node.name] = signature(node)
        elif isinstance(node, ast.ClassDef):
            result[node.name] = {
                "bases": [ast.unparse(base) for base in node.bases],
                "decorators": [ast.unparse(item) for item in node.decorator_list],
                "fields": [ast.unparse(item) for item in node.body if isinstance(item, ast.AnnAssign)],
                "methods": {item.name: signature(item) for item in node.body
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and (not item.name.startswith("_") or item.name == "__init__")},
            }
    return result


def external_imports(tree):
    result = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.module.startswith("hermes_db"):
            if node.module.split(".")[0] in {"agent", "gateway", "hermes_cli", "hermes_state",
                    "hermes_state_messages", "hermes_state_queries", "hermes_constants", "hermes_platform",
                    "plugins", "tools", "tui_gateway", "cron"} or node.module.startswith("hermes_state_"):
                result.append({"module": node.module, "symbols": [item.name for item in node.names], "line": node.lineno})
    return sorted(result, key=lambda item: (item["module"], item["line"]))


def source_inventory(blobs):
    surfaces, dependencies, anchors = {}, {}, {}
    for name, content in sorted(blobs.items()):
        tree = ast.parse(content, filename=name)
        surface = definitions(tree)
        if surface:
            surfaces[name] = surface
        edges = external_imports(tree)
        if edges:
            dependencies[name] = edges
        if name.startswith(("hermes_db/migrations/versions/", "hermes_db/tables/")):
            anchors[name] = {"sha256": hashlib.sha256(content).hexdigest()}
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                            anchors[name][target.id] = ast.literal_eval(node.value)
    return surfaces, dependencies, anchors


def references():
    strings, dynamic = {}, {}
    tracked = git("ls-files", "*.py").decode().splitlines()
    for name in tracked:
        path = ROOT / name
        content = path.read_bytes()
        if b"hermes_db" not in content:
            continue
        tree = ast.parse(content, filename=name)
        literals, calls = [], []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and "hermes_db." in node.value:
                literals.append({"line": node.lineno, "value": node.value})
            if name.startswith("hermes_db/") and isinstance(node, ast.Call):
                function = ast.unparse(node.func)
                if function in {"import_module", "__import__", "getattr"}:
                    calls.append({"line": node.lineno, "call": ast.unparse(node)})
        if literals:
            strings[name] = sorted(literals, key=lambda item: item["line"])
        if calls:
            dynamic[name] = sorted(calls, key=lambda item: item["line"])
    return strings, dynamic


def main():
    mapping = json.loads((ROOT / "docs/designs/hermes-db-package-map.json").read_text(encoding="utf-8-sig"))
    archive = git("archive", "--format=tar", mapping["baseline"], "hermes_db")
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        blobs = {member.name: source.extractfile(member).read() for member in source.getmembers()
                 if member.isfile() and member.name.endswith(".py")}
    expected = {item["source"]: item["sha256"] for item in mapping["files"]}
    actual = {name: hashlib.sha256(content).hexdigest() for name, content in blobs.items()}
    if actual != expected:
        raise SystemExit("Frozen mapping does not match baseline Git blobs")
    names = {path.relative_to(ROOT).as_posix() for path in (ROOT / "hermes_db").rglob("*.py")}
    if names != set(expected) or git("diff", mapping["baseline"], "--", "hermes_db").strip():
        raise SystemExit("Current hermes_db differs from the frozen baseline; reconcile mapping first")
    surfaces, dependencies, anchors = source_inventory(blobs)
    strings, dynamic = references()
    registries = {}
    for name in ("hermes_db/domains/catalog.py", "hermes_db/settings.py", "hermes_db/schema.py"):
        tree = ast.parse(blobs[name])
        registries[name] = [ast.unparse(node) for node in tree.body
                           if isinstance(node, (ast.Assign, ast.AnnAssign))]
    result = {"baseline": mapping["baseline"], "planning_commit": git("rev-parse", "HEAD").decode().strip(),
              "kind": "historical Task1 baseline; paths describe pre-refactor code",
              "public_definitions": surfaces, "project_imports": dependencies,
              "dynamic_calls": dynamic, "module_string_references": strings,
              "schema_anchors": anchors, "registries": registries,
              "identity_definitions": {name: definitions(ast.parse((ROOT / name).read_bytes()))
                   for name in ("hermes_cli/projects_db.py", "hermes_cli/kanban_db.py",
                                "hermes_cli/kanban_errors.py", "gateway/hosted_rooms.py",
                                "agent/verification_evidence.py", "plugins/plugin_storage_types.py")},
              "internal_imports": {name: [ast.unparse(node) for node in ast.walk(ast.parse(content))
                   if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("hermes_db")]
                   for name, content in sorted(blobs.items())},
              "boundary_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                   for name in ("hermes_cli/data/plugin_api.json", "scripts/boundary_lint_baseline.json")}}
    reference_keys = ("project_imports", "internal_imports", "dynamic_calls", "module_string_references")
    reference_data = {key: result.pop(key) for key in reference_keys}
    reference_data["baseline"] = mapping["baseline"]
    reference_data["kind"] = result["kind"]
    reference_name = "hermes-db-package-reference-baseline.json"
    (ROOT / "docs/designs" / reference_name).write_text(
        json.dumps(reference_data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    result["references"] = reference_name
    destination = ROOT / "docs/designs/hermes-db-package-baseline.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Verified {len(blobs)} module hashes; froze {len(surfaces)} surfaces, "
          f"{len(dependencies)} dependency owners, {len(anchors)} schema/package anchors")


if __name__ == "__main__":
    main()
