#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重新生成 manifest.json 并打包成可分发的 zip。

    python3 bin/package.py                # -> dist/ielts-practice-export-<version>.zip
    python3 bin/package.py --no-zip       # 只更新 manifest

改完脚本/文档后跑一次，保证 manifest 里的哈希与文件一致。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "ielts-practice-export"
EXCLUDE_DIRS = {"__pycache__", ".git", "dist", ".cache", "ielts-data"}
EXCLUDE_SUFFIX = {".pyc", ".pyo"}


def version() -> str:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    m = re.search(r"^version:\s*([0-9.]+)\s*$", text, re.M)
    return m.group(1) if m else "0.0.0"


def schema_version() -> str:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    m = re.search(r'^schema_version:\s*"?([0-9.]+)"?\s*$', text, re.M)
    return m.group(1) if m else "1.0"


def walk():
    for p in sorted(ROOT.rglob("*")):
        if p.is_dir():
            continue
        if any(part in EXCLUDE_DIRS for part in p.relative_to(ROOT).parts):
            continue
        if p.suffix in EXCLUDE_SUFFIX:
            continue
        yield p


def sha256(p: Path) -> str:
    """文本文件按 LF 归一后取哈希，与 git 入库内容一致（避免 CRLF 造成假不一致）。"""
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            if p.suffix.lower() not in {".zip", ".png", ".jpg", ".jpeg", ".gif"}:
                chunk = chunk.replace(b"\r\n", b"\n")
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-zip", action="store_true")
    args = ap.parse_args(argv)

    files = []
    for p in walk():
        rel = p.relative_to(ROOT).as_posix()
        if rel == "manifest.json":
            continue
        files.append({"path": rel, "bytes": p.stat().st_size, "sha256": sha256(p)[:16]})

    manifest = {
        "name": NAME,
        "version": version(),
        "schema_version": schema_version(),
        "built_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python": ">=3.8",
        "dependencies": [],
        "entrypoints": {"workbuddy": "SKILL.md", "generic": "AGENTS.md",
                        "human": "README.md", "porting": "PORTING.md"},
        "requires": {
            "network": ["https://www.idictation.cn"],
            "auth": "idictation_session cookie（本人账号）",
            "disk": "每 100 篇约 10–20 MB（含原文与语法）",
        },
        "commands": {
            "selftest": "python3 tests/selftest.py",
            "export": "python3 scripts/export.py --out ./ielts-data",
            "validate": "python3 scripts/validate.py --in ./ielts-data",
            "install": "python3 bin/install.py",
        },
        "file_count": len(files),
        "files": files,
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("manifest.json 已更新：%d 个文件，版本 %s（schema %s）"
          % (len(files), manifest["version"], manifest["schema_version"]))

    if args.no_zip:
        return 0

    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    zpath = dist / ("%s-%s.zip" % (NAME, manifest["version"]))
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in walk():
            rel = p.relative_to(ROOT).as_posix()
            if rel == "manifest.json":
                continue
            z.write(p, (NAME + "/" + rel))
        z.write(ROOT / "manifest.json", NAME + "/manifest.json")
    print("已打包：%s（%.1f KB）" % (zpath, zpath.stat().st_size / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
