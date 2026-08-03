#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]

parser = argparse.ArgumentParser(description="Regenerate repository URLs in TVBox manifests")
parser.add_argument("--repo", required=True, help="GitHub repository, for example user/repo")
args = parser.parse_args()
records = json.loads((ROOT / "spider_validation.json").read_text(encoding="utf-8"))
base = f"https://raw.githubusercontent.com/{args.repo}/refs/heads/main/"
urls = [base + quote(item["file"], safe="/") for item in records if item["valid"]]
v2 = [{key: item[key] for key in ("id", "version", "file", "valid")} for item in records]
sites = {
    "spider": "",
    "sites": [
        {
            "key": item["id"], "name": item["name"], "type": 3,
            "api": base + quote(item["file"], safe="/"),
            "searchable": 1, "quickSearch": 1, "filterable": 1,
        }
        for item in records if item["valid"]
    ],
}
for name, value in (("spiders.json", urls), ("spiders_v2.json", v2), ("sites.json", sites)):
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Updated manifests for {args.repo}: {len(urls)} spiders")
