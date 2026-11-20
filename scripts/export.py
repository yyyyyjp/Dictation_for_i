#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ielts-practice-export 主程序：抓取 → 归一化 → 落盘。

用法::

    python scripts/export.py --out ./ielts-data                 # 只导做过的
    python scripts/export.py --out ./ielts-data --include-undone # 含未做篇目（答案库）
    python scripts/export.py --out ./ielts-data --modules reading --books 剑雅18,剑雅19
    python scripts/export.py --out ./ielts-data --keep-raw --csv

退出码：0 成功；2 登录态失效；3 网络失败；4 无数据。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import idict_client as ic          # noqa: E402
import normalize as nz             # noqa: E402
import summary as sm               # noqa: E402

VERSION = "1.0.0"


# ------------------------------------------------------------------ CLI
def build_parser():
    p = argparse.ArgumentParser(
        prog="ielts-practice-export",
        description="导出 idictation.cn 的雅思阅读/听力/写作作答数据，并归一化为可分析的 JSONL。")
    p.add_argument("--out", default="./ielts-data", help="输出目录（默认 ./ielts-data）")
    p.add_argument("--modules", default="reading,listening,writing",
                   help="要导出的科目，逗号分隔：reading,listening,writing")
    p.add_argument("--books", default="", help="只导出这些套书，逗号分隔，如 剑雅18,剑雅19 或 18,19")
    p.add_argument("--include-undone", action="store_true",
                   help="未做过的篇目也抓（用于建立全库答案库/统计题型分布）")
    p.add_argument("--reading-source", default="jianya", choices=["jianya", "g", "both"],
                   help="阅读题库：剑雅 A 类 / G 类 / 两者")
    p.add_argument("--listening-source", default="jianya", choices=["jianya", "jijing", "both"],
                   help="听力题库：剑雅真题 / 机经 / 两者")
    p.add_argument("--writing-module", default="zhenti", choices=["zhenti", "jijing", "g"],
                   help="写作题库来源")
    p.add_argument("--writing-kinds", default="dazuowen,xiaozuowen",
                   help="写作类型：dazuowen,xiaozuowen")
    p.add_argument("--cookie", default=None, help="idictation_session 的值")
    p.add_argument("--cookie-file", default=None, help="存放 cookie 的文件")
    p.add_argument("--limit", type=int, default=0, help="每个科目最多处理多少个单元（调试用）")
    p.add_argument("--workers", type=int, default=4, help="并发请求数（默认 4，别设太大）")
    p.add_argument("--keep-raw", action="store_true", help="把每个接口的原始响应存到 raw/")
    p.add_argument("--csv", action="store_true", help="额外输出 questions.csv（Excel 友好）")
    p.add_argument("--no-cache", action="store_true", help="不使用 out/.cache 缓存")
    p.add_argument("--dry-run", action="store_true", help="只拉目录并打印统计，不抓详情")
    p.add_argument("--quiet", action="store_true", help="不打印进度")
    return p


def log(msg, quiet=False):
    if not quiet:
        print(msg, file=sys.stderr, flush=True)


def norm_book(s: str) -> str:
    s = s.strip()
    return "剑雅" + s if s.isdigit() else s


# ------------------------------------------------------------------ 抓取
def pick(items, books, include_undone, limit):
    out = []
    for it in items:
        if books and (it.get("book") or "") not in books:
            continue
        if not include_undone and not it.get("done"):
            continue
        out.append(it)
    return out[:limit] if limit else out


def fetch_reading(cli, items, args, raw_dir, errors):
    """一篇阅读一次请求。"""
    out = {"passages": [], "attempts": [], "groups": [], "questions": []}
    total = len(items)
    done_n = 0

    def work(it):
        v = cli.reading_part(it["part_id"], source=it.get("source", "jianya"))
        if not v:
            raise ValueError("空响应（part_id=%s）" % it["part_id"])
        return it, v

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(work, it): it for it in items}
        for fut in as_completed(futures):
            it = futures[fut]
            done_n += 1
            try:
                _, v = fut.result()
                ent = nz.reading_entities(v, it)
                out["passages"].append(ent["passage"])
                out["groups"].extend(ent["groups"])
                out["questions"].extend(ent["questions"])
                if ent["attempt"]:
                    out["attempts"].append(ent["attempt"])
                if args.keep_raw:
                    save_raw(raw_dir / "reading" / ("%s.json" % it["part_id"]), v)
            except Exception as e:  # noqa: BLE001
                errors.append("reading %s %s %s: %s" % (it.get("book"), it.get("test"),
                                                        it.get("title"), e))
            if done_n % 20 == 0 or done_n == total:
                log("  阅读 %d/%d" % (done_n, total), args.quiet)
    return out


def fetch_listening(cli, items, args, raw_dir, errors):
    """剑雅：一个 Test 一次请求，按 Part 拆 attempt；机经：一个 Part 一次请求。"""
    out = {"passages": [], "attempts": [], "groups": [], "questions": []}
    jianya = [i for i in items if i.get("source") != "jijing"]
    jijing = [i for i in items if i.get("source") == "jijing"]

    if jianya:
        by_test = {}
        for it in jianya:
            by_test.setdefault(it.get("test_id"), []).append(it)
        total, done_n = len(by_test), 0

        def work(test_id, group):
            v = cli.listening_test(test_id)
            if not v:
                raise ValueError("空响应（test_id=%s）" % test_id)
            return group, v

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(work, tid, g): tid for tid, g in by_test.items()}
            for fut in as_completed(futures):
                tid = futures[fut]
                done_n += 1
                try:
                    group, v = fut.result()
                    ent = nz.listening_entities(v, group)
                    out["passages"].extend(ent["passages"])
                    out["groups"].extend(ent["groups"])
                    out["questions"].extend(ent["questions"])
                    out["attempts"].extend(ent["attempts"])
                    if args.keep_raw:
                        save_raw(raw_dir / "listening" / ("%s.json" % tid), v)
                except Exception as e:  # noqa: BLE001
                    errors.append("listening test_id=%s: %s" % (tid, e))
                if done_n % 10 == 0 or done_n == total:
                    log("  听力 Test %d/%d" % (done_n, total), args.quiet)

    if jijing:
        total, done_n = len(jijing), 0

        def work_jj(it):
            v = cli.listening_part(it["part_id"])
            if not v:
                raise ValueError("空响应（paper_id=%s）" % it["part_id"])
            wrap = {"jianya_name": it.get("book"), "test_name": it.get("test"),
                    "test_id": it.get("test_id"), "parts": [v]}
            return it, wrap

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(work_jj, it): it for it in jijing}
            for fut in as_completed(futures):
                it = futures[fut]
                done_n += 1
                try:
                    item, wrap = fut.result()
                    ent = nz.listening_entities(wrap, [item])
                    out["passages"].extend(ent["passages"])
                    out["groups"].extend(ent["groups"])
                    out["questions"].extend(ent["questions"])
                    out["attempts"].extend(ent["attempts"])
                    if args.keep_raw:
                        save_raw(raw_dir / "listening" / ("jj_%s.json" % it["part_id"]), wrap)
                except Exception as e:  # noqa: BLE001
                    errors.append("listening jijing paper_id=%s: %s" % (it.get("part_id"), e))
                if done_n % 10 == 0 or done_n == total:
                    log("  机经 %d/%d" % (done_n, total), args.quiet)
    return out


def fetch_writing(cli, args, raw_dir, errors):
    out = {"writing": [], "attempts": [], "questions": [], "groups": [], "passages": [],
           "user_id": None}
    kinds = {k.strip() for k in args.writing_kinds.split(",") if k.strip()}
    page, rows = 1, []
    while True:
        v = cli.writing_results(module=args.writing_module, page=page, limit=50)
        batch = v.get("list") or []
        rows.extend(batch)
        if len(batch) < 50 or page >= 20:
            break
        page += 1

    seen = set()
    for it in rows:
        out["user_id"] = out["user_id"] or it.get("user_id")
        kind = it.get("kind")
        if kind and kind not in kinds:
            continue
        if it.get("id") in seen:
            continue
        seen.add(it.get("id"))
        try:
            r = cli.writing_result(it["id"], module=args.writing_module)
            if not r:
                r = it
            out["writing"].append(nz.writing_entity(r))
            if args.keep_raw:
                save_raw(raw_dir / "writing" / ("%s.json" % it["id"]), r)
        except Exception as e:  # noqa: BLE001
            errors.append("writing result_id=%s: %s" % (it.get("id"), e))
    return out


# ------------------------------------------------------------------ 落盘
def save_raw(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    return len(rows)


def write_csv(path: Path, rows):
    cols = ["question_id", "attempt_id", "module", "book", "test", "part", "part_index",
            "q_number", "question_type", "question_type_zh", "stem",
            "yours", "correct_answer", "is_correct", "state",
            "error_tags", "note"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            row = {k: r.get(k) for k in cols}
            row["error_tags"] = "、".join(r.get("error_tags") or [])
            w.writerow(row)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def sort_key(r):
    return (r.get("book") or "", r.get("test") or "",
            r.get("part_index") or 0, nz.num(r.get("q_number")))


# ------------------------------------------------------------------ main
def main(argv=None):
    args = build_parser().parse_args(argv)
    t0 = time.time()
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    modules = [m.strip() for m in args.modules.split(",") if m.strip()]
    books = {norm_book(b) for b in args.books.split(",") if b.strip()}
    errors = []

    try:
        cli = ic.IdictClient(ic.resolve_cookie(args.cookie, args.cookie_file),
                             cache_dir=None if args.no_cache else str(out / ".cache"))
    except ic.AuthError as e:
        print(str(e), file=sys.stderr)
        return 2

    data = {"passages": [], "attempts": [], "groups": [], "questions": [],
            "writing": [], "catalog": []}
    raw_dir = out / "raw"

    # ---------------- 目录
    log("读取目录…", args.quiet)
    read_items, listen_items, write_items = [], [], []
    if "reading" in modules:
        sources = ["jianya", "g"] if args.reading_source == "both" else [args.reading_source]
        for src in sources:
            try:
                read_items.extend(ic.flatten_catalog(cli.reading_catalog(src), "reading", src))
            except Exception as e:  # noqa: BLE001
                errors.append("reading catalog(%s): %s" % (src, e))
    if "listening" in modules:
        sources = ["jianya", "jijing"] if args.listening_source == "both" else [args.listening_source]
        for src in sources:
            try:
                listen_items.extend(ic.flatten_catalog(cli.listening_catalog(src), "listening", src))
            except Exception as e:  # noqa: BLE001
                errors.append("listening catalog(%s): %s" % (src, e))
    if "writing" in modules:
        for kind in [k.strip() for k in args.writing_kinds.split(",") if k.strip()]:
            try:
                rows = ic.flatten_catalog(cli.writing_catalog(kind, args.writing_module),
                                          "writing", args.writing_module)
                for r in rows:
                    r["kind"] = kind
                write_items.extend(rows)
            except Exception as e:  # noqa: BLE001
                errors.append("writing catalog(%s): %s" % (kind, e))

    for it in read_items + listen_items + write_items:
        data["catalog"].append(nz.catalog_row(it))

    def count(rows, pred):
        return sum(1 for r in rows if pred(r))

    log("目录：阅读 %d（已做 %d）｜听力 %d（已做 %d）｜写作 %d（已做 %d）"
        % (len(read_items), count(read_items, lambda r: r["done"]),
           len(listen_items), count(listen_items, lambda r: r["done"]),
           len(write_items), count(write_items, lambda r: r["done"])), args.quiet)

    if args.dry_run:
        print(json.dumps({"reading": len(read_items), "listening": len(listen_items),
                          "writing": len(write_items),
                          "reading_done": count(read_items, lambda r: r["done"]),
                          "listening_done": count(listen_items, lambda r: r["done"]),
                          "writing_done": count(write_items, lambda r: r["done"])},
                         ensure_ascii=False, indent=2))
        return 0

    # ---------------- 详情
    if "reading" in modules:
        items = pick(read_items, books, args.include_undone, args.limit)
        log("抓取阅读 %d 篇…" % len(items), args.quiet)
        part = fetch_reading(cli, items, args, raw_dir, errors)
        for k in ("passages", "attempts", "groups", "questions"):
            data[k].extend(part[k])

    if "listening" in modules:
        items = pick(listen_items, books, args.include_undone, args.limit)
        log("抓取听力 %d 个 Part（%d 个 Test）…"
            % (len(items), len({i.get("test_id") for i in items})), args.quiet)
        part = fetch_listening(cli, items, args, raw_dir, errors)
        for k in ("passages", "attempts", "groups", "questions"):
            data[k].extend(part[k])

    if "writing" in modules:
        log("抓取写作…", args.quiet)
        part = fetch_writing(cli, args, raw_dir, errors)
        data["writing"].extend(part["writing"])
        account_id = part.get("user_id")
    else:
        account_id = None

    # ---------------- 排序与落盘
    data["attempts"].sort(key=sort_key)
    data["questions"].sort(key=sort_key)
    data["groups"].sort(key=lambda r: (r.get("book") or "", r.get("test") or "",
                                       r.get("part_index") or 0, nz.num(r.get("group_id"))))
    data["passages"].sort(key=sort_key)
    data["writing"].sort(key=lambda r: (r.get("essay", {}).get("submitted_at") or ""))

    counts = {
        "attempts": write_jsonl(out / "attempts.jsonl", data["attempts"]),
        "questions": write_jsonl(out / "questions.jsonl", data["questions"]),
        "groups": write_jsonl(out / "groups.jsonl", data["groups"]),
        "passages": write_jsonl(out / "passages.jsonl", data["passages"]),
        "writing": write_jsonl(out / "writing.jsonl", data["writing"]),
        "catalog": write_jsonl(out / "catalog.jsonl", data["catalog"]),
    }
    if args.csv:
        write_csv(out / "questions.csv", data["questions"])

    meta = {
        "schema_version": nz.SCHEMA_VERSION,
        "generator": {"name": "ielts-practice-export", "version": VERSION},
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": {"platform": "idictation.cn", "base": ic.BASE,
                   "note": "接口为站点前端私有契约，改版可能失效"},
        "scope": {"modules": modules, "books": sorted(books) or None,
                  "include_undone": bool(args.include_undone),
                  "reading_source": args.reading_source,
                  "listening_source": args.listening_source,
                  "writing_module": args.writing_module},
        "counts": counts,
        "account": {"user_id": account_id or _guess_user(data)},
        "conventions": {
            "accuracy": "0-1 浮点；站点原值见 accuracy_raw",
            "time": "提交时间为站点返回的 UTC 字符串，用时单位为秒",
            "id": "module:part_id[:result_id]，可跨次导出稳定重建",
            "state": "correct | wrong | blank（交卷未填）| unattempted（未做）",
        },
        "warnings": errors,
        "files": [],
    }
    for name in ("attempts.jsonl", "questions.jsonl", "groups.jsonl",
                 "passages.jsonl", "writing.jsonl", "catalog.jsonl"):
        p = out / name
        if p.is_file():
            meta["files"].append({"name": name, "bytes": p.stat().st_size, "sha256": sha256(p)})

    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(
        sm.build_summary(data["attempts"], data["questions"], data["passages"],
                         data["writing"], data["catalog"], meta), encoding="utf-8")
    (out / "analysis_prompt.md").write_text(sm.build_prompt(meta), encoding="utf-8")

    elapsed = time.time() - t0
    print(json.dumps({
        "out": str(out),
        "files": counts,
        "http_calls": cli.calls,
        "cache_hits": cli.cache_hits,
        "warnings": len(errors),
        "elapsed_sec": round(elapsed, 1),
    }, ensure_ascii=False, indent=2))
    if errors:
        log("有 %d 条告警，详见 meta.json 的 warnings" % len(errors), args.quiet)
    return 0 if (counts["attempts"] or counts["questions"]) else 4


def _guess_user(data):
    for a in data["attempts"]:
        if a.get("user_id"):
            return a["user_id"]
    return None


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ic.AuthError as e:      # noqa: F821
        print(str(e), file=sys.stderr)
        sys.exit(2)
    except ConnectionError as e:
        print(str(e), file=sys.stderr)
        sys.exit(3)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:              # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
