#!/usr/bin/env python3
"""Lightweight repo triage:
- read README.* if present
- detect dominant languages (by file extension)
- compute a content hash for change tracking
"""
import os, hashlib, json, sys
from pathlib import Path
from collections import Counter

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("third_party")
out = []

def file_hash(p: Path):
  h = hashlib.sha256()
  with p.open("rb") as f:
    while True:
      b = f.read(1024*1024)
      if not b: break
      h.update(b)
  return h.hexdigest()

for repo in sorted([p for p in ROOT.iterdir() if p.is_dir()]):
  exts = Counter()
  readme = None
  for p in repo.rglob("*"):
    if p.is_file():
      exts[p.suffix.lower()] += 1
      if p.name.lower().startswith("readme") and readme is None:
        readme = p
  dominant = [e for e,_ in exts.most_common(8)]
  rh = file_hash(readme) if readme else ""
  out.append({
    "repo": repo.name,
    "dominant_exts": dominant,
    "readme_path": str(readme) if readme else "",
    "readme_hash": rh,
  })

print(json.dumps(out, indent=2))
