#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出结果结构校验（零依赖）：检查 JSONL 可解析、必填字段齐全、枚举合法、ID 不重复。

    python scripts/validate.py --in ./ielts-data

退出码 0 全部通过；1 有错误（错误会逐条打印，最多 20 条）。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REQUIRED = {
    "questions.jsonl": ("schema_version", "question_id", "module", "state", "q_number"),
    "attempts.jsonl": ("schema_version", "attempt_id", "module", "total", "correct"),
    "passages.jsonl": ("schema_version", "passage_id", "module", "sentences"),
    "groups.jsonl": ("schema_version", "group_id", "module", "instruction"),
    "writing.jsonl": ("schema_version", "writing_id", "task", "essay"),
    "catalog.jsonl": ("schema_version", "module", "part_id", "done"),
}
UNIQUE = {"questions.jsonl": "question_id", "attempts.jsonl": "attempt_id",
          "passages.jsonl": "passage_id", "groups.jsonl": "group_id",
          "writing.jsonl": "writing_id"}
STATES = {"correct", "wrong", "blank", "unattempted"}


def check_file(path: Path, errors: list, warns: list):
    name = path.name
    rows, bad_json = [], 0
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                bad_json += 1
                errors.append("%s:%d JSON 解析失败: %s" % (name, i, e))
    if bad_json:
        return rows

    for i, r in enumerate(rows, 1):
        for k in REQUIRED[name]:
            if k not in r:
                errors.append("%s:%d 缺字段 %s" % (name, i, k))
        if name == "questions.jsonl":
            if r.get("state") not in STATES:
                errors.append("%s:%d state 非法: %r" % (name, i, r.get("state")))
            if r.get("state") == "correct" and r.get("is_correct") is not True:
                errors.append("%s:%d state=correct 但 is_correct != true" % (name, i))
            if r.get("state") == "wrong" and r.get("is_correct") is not False:
                errors.append("%s:%d state=wrong 但 is_correct != false" % (name, i))
            if r.get("state") == "unattempted" and r.get("is_correct") is not None:
                errors.append("%s:%d state=unattempted 但 is_correct 非 null" % (name, i))
            qid = str(r.get("question_id") or "")
            if qid and qid.count(":") < 2:
                errors.append("%s:%d question_id 不符合 module:part_id:qid" % (name, i))
        if name == "attempts.jsonl":
            if isinstance(r.get("total"), int) and r["total"] > 0:
                if not (0 <= (r.get("correct") or 0) <= r["total"]):
                    errors.append("%s:%d correct 越界" % (name, i))
            d = r.get("duration_sec")
            if d is not None and not isinstance(d, (int, float)):
                warns.append("%s:%d duration_sec 非数值" % (name, i))

    key = UNIQUE.get(name)
    if key:
        dup = [k for k, v in Counter(r.get(key) for r in rows).items() if v > 1]
        if dup:
            errors.append("%s: %s 重复 %d 个，例如 %s" % (name, key, len(dup), dup[:3]))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="./ielts-data")
    args = ap.parse_args(argv)
    src = Path(args.src).expanduser()

    if not src.is_dir():
        print("目录不存在: %s" % src, file=sys.stderr)
        return 1

    errors, warns = [], []
    print("校验 %s\n" % src)
    for name in REQUIRED:
        p = src / name
        if not p.is_file():
            warns.append("%s 不存在（可能未导出该科目）" % name)
            continue
        rows = check_file(p, errors, warns)
        print("  %-18s %6d 行" % (name, len(rows)))

    for w in warns[:10]:
        print("  WARN  " + w)
    for e in errors[:20]:
        print("  ERR   " + e)
    if len(errors) > 20:
        print("  ... 另有 %d 条错误" % (len(errors) - 20))
    print("\n%s" % ("通过" if not errors else "失败：%d 个错误" % len(errors)))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
