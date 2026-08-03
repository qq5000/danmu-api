#!/usr/bin/env python3
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_DIR = ROOT / "py"
REQUIRED = {"init", "homeContent", "homeVideoContent", "categoryContent", "detailContent", "searchContent", "playerContent"}
errors = []
ids = set()
for path in sorted(PY_DIR.glob("*.py")):
    text = path.read_text(encoding="utf-8-sig")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as error:
        errors.append(f"{path.name}: syntax error: {error}")
        continue
    spider = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Spider"), None)
    if spider is None:
        errors.append(f"{path.name}: missing Spider class")
        continue
    methods = {node.name for node in spider.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    missing = REQUIRED - methods
    if missing:
        errors.append(f"{path.name}: missing methods: {', '.join(sorted(missing))}")
    match = re.search(r"^#\s*//@id:([0-9a-f]{40})$", text, re.MULTILINE)
    if not match:
        errors.append(f"{path.name}: missing 40-character id metadata")
    elif match.group(1) in ids:
        errors.append(f"{path.name}: duplicate id {match.group(1)}")
    else:
        ids.add(match.group(1))

records = json.loads((ROOT / "spider_validation.json").read_text(encoding="utf-8"))
files = {f"py/{path.name}" for path in PY_DIR.glob("*.py")}
manifest_files = {item["file"] for item in records}
if files != manifest_files:
    errors.append("spider_validation.json does not match py directory")

if errors:
    print("\n".join(errors))
    sys.exit(1)
print(f"PASS: {len(files)} Python spiders passed syntax, interface and manifest checks")
