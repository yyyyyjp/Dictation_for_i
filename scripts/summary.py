#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""由归一化数据生成人读的 summary.md 与可直接粘贴的分析指令。

刻意不引入 pandas：输出是给人/模型看的 Markdown，不是 BI 报表。
"""

from __future__ import annotations

from collections import Counter, defaultdict


def _pct(x):
    return "—" if x is None else "%.1f%%" % (x * 100)


def _fmt_sec(s):
    if s is None:
        return "—"
    s = int(s)
    return "%d:%02d" % (s // 60, s % 60)


def _table(headers, rows):
    if not rows:
        return "（无数据）\n"
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) if x is not None else "—" for x in r) + " |")
    return "\n".join(out) + "\n"


def build_summary(attempts, questions, passages, writing, catalog, meta) -> str:
    L = []
    seq = [0]

    def sec(title):
        seq[0] += 1
        L.append("## %d. %s\n" % (seq[0], title))

    mod = Counter(a["module"] for a in attempts)
    q_total = len(questions)
    attempted_q = [q for q in questions if q["state"] in ("correct", "wrong", "blank")]
    correct = sum(1 for q in questions if q["is_correct"])

    L.append("# 雅思练习数据总览\n")
    L.append("> 由 `ielts-practice-export` 自动生成；schema v%s，导出于 %s。\n"
             % (meta["schema_version"], meta["exported_at"]))

    sec("概览")
    L.append(_table(["指标", "值"], [
        ["练习单元（attempt）", len(attempts) + len(writing)],
        ["阅读 / 听力 / 写作", "%d / %d / %d" % (mod.get("reading", 0), mod.get("listening", 0), len(writing))],
        ["题目总数（含未做）", q_total],
        ["已作答题目", len([q for q in attempted_q if q["state"] in ("correct", "wrong")])],
        ["答对", correct],
        ["整体正确率（分母含空答）", _pct(correct / len(attempted_q) if attempted_q else None)],
        ["原文/转写篇数", len(passages)],
        ["目录条目", len(catalog)],
        ["有作答记录的书", len({a["book"] for a in attempts if a.get("book")})],
    ]))

    # ---- 分科
    sec("分科表现")
    rows = []
    for m in ("reading", "listening", "writing"):
        if m == "writing":
            ds = [w["essay"].get("duration_sec") for w in writing if w["essay"].get("duration_sec")]
            rows.append(["writing", len(writing), "—", "—",
                         _fmt_sec(sum(ds) // len(ds)) if ds else "—"])
            continue
        aa = [a for a in attempts if a["module"] == m]
        qs = [q for q in questions if q["module"] == m and q["is_correct"] is not None]
        acc = (sum(1 for q in qs if q["is_correct"]) / len(qs)) if qs else None
        durations = [a["duration_sec"] for a in aa if a.get("duration_sec")]
        rows.append([m, len(aa), len(qs), _pct(acc),
                     _fmt_sec(sum(durations) // len(durations)) if durations else "—"])
    L.append(_table(["科目", "练习次数", "计分题数（含空答）", "正确率", "平均用时"], rows))

    # ---- 分题型
    sec("分题型")
    bucket = defaultdict(lambda: [0, 0])
    for q in questions:
        if q["is_correct"] is None:
            continue
        b = bucket[(q["question_type"], q["question_type_zh"])]
        b[1] += 1
        b[0] += 1 if q["is_correct"] else 0
    rows = [[k[1], k[0], v[1], _pct(v[0] / v[1] if v[1] else None)]
            for k, v in sorted(bucket.items(), key=lambda x: -x[1][1])]
    L.append(_table(["题型", "type_key", "题数", "正确率"], rows))

    # ---- 分位置
    sec("分位置（阅读 P1–P3 / 听力 Part 1–4）")
    pos = defaultdict(lambda: [0, 0])
    for q in questions:
        if q["is_correct"] is None or q.get("part_index") is None:
            continue
        key = (q["module"], q["part_index"])
        pos[key][1] += 1
        pos[key][0] += 1 if q["is_correct"] else 0
    rows = [["阅读 P%s" % k[1] if k[0] == "reading" else "听力 Part %s" % k[1],
             v[1], _pct(v[0] / v[1] if v[1] else None)]
            for k, v in sorted(pos.items())]
    L.append(_table(["位置", "题数", "正确率"], rows))

    # ---- 分书
    sec("分套书")
    bk = defaultdict(lambda: [0, 0])
    for q in questions:
        if q["is_correct"] is None:
            continue
        b = bk[q.get("book") or "未知"]
        b[1] += 1
        b[0] += 1 if q["is_correct"] else 0
    rows = [[k, v[1], _pct(v[0] / v[1] if v[1] else None)]
            for k, v in sorted(bk.items(), key=lambda x: -x[1][1])]
    L.append(_table(["套书", "题数", "正确率"], rows))

    # ---- 错题
    wrong = [q for q in questions if q["state"] in ("wrong", "blank")]
    wrong.sort(key=lambda q: (q.get("book") or "", q.get("test") or "", q.get("part") or "",
                              q["q_number"] if isinstance(q["q_number"], (int, float)) else 0))
    sec("错题清单（最多 60 条）")
    rows = [[q.get("book"), q.get("test"), q.get("part"), q.get("q_number"),
             q.get("question_type_zh"), (q.get("yours") or "").strip() or "（空）",
             q.get("correct_answer"),
             "、".join(str(x) for x in (q.get("error_tags") or [])) or "—"]
            for q in wrong[:60]]
    L.append(_table(["套书", "Test", "Part", "题号", "题型", "我的答案", "正确答案", "自标错因"], rows))
    if len(wrong) > 60:
        L.append("> 另有 %d 条错题，见 `questions.jsonl` 中 `state != \"correct\"` 的行。\n"
                 % (len(wrong) - 60))

    tags = Counter(t for q in questions for t in (q.get("error_tags") or []))
    if tags:
        L.append("### 自标错因分布\n")
        L.append(_table(["错因标签", "题数"],
                        [[k, v] for k, v in tags.most_common()]))

    # ---- 用时
    sec("用时最长的练习")
    slow = sorted([a for a in attempts if a.get("duration_sec")],
                  key=lambda a: -a["duration_sec"])[:8]
    L.append(_table(["套书", "Test", "Part", "用时", "正确率"],
                    [[a.get("book"), a.get("test"), a.get("part"),
                      _fmt_sec(a["duration_sec"]), _pct(a.get("accuracy"))] for a in slow]))

    # ---- 写作
    if writing:
        sec("写作")
        rows = []
        for w in writing:
            m = w["scoring"]["models"]
            rows.append([w.get("book") or "—", w["paper_name"], w["kind_zh"],
                         w["essay"].get("word_count"),
                         w["scoring"].get("total_score"),
                         "、".join("%s:%s" % (k, v.get("band")) for k, v in m.items()) or "—",
                         (w["scoring"].get("consensus") or {}).get("band_mean")])
        L.append(_table(["套书", "题目", "类型", "词数", "总分", "各模型 band", "均值"], rows))

    # ---- 数据覆盖
    sec("数据覆盖度")
    def coverage(key, rows_):
        if not rows_:
            return "—"
        n = sum(1 for r in rows_ if r.get(key) not in (None, "", [], {}))
        return "%d/%d" % (n, len(rows_))
    L.append(_table(["字段", "有值比例"], [
        ["题干 stem", coverage("stem", questions)],
        ["正确答案", coverage("correct_answer", questions)],
        ["官方定位词 locating", "%d/%d" % (sum(1 for q in questions if q["evidence"]["locating"]), len(questions))],
        ["中心句 central_sentences", "%d/%d" % (sum(1 for q in questions if q["evidence"]["central_sentences"]), len(questions))],
        ["AI 解析", "%d/%d" % (sum(1 for q in questions if q["evidence"]["ai"] or q["evidence"]["ai_analysis"]), len(questions))],
        ["句子翻译", "%d/%d" % (sum(1 for p in passages for s in p["sentences"] if s.get("translation")),
                               sum(len(p["sentences"]) for p in passages))],
        ["语法分析", "%d/%d" % (sum(1 for p in passages for s in p["sentences"] if s.get("grammar")),
                              sum(len(p["sentences"]) for p in passages))],
        ["音频直链", "%d/%d" % (sum(1 for p in passages if p.get("audio")), len(passages))],
        ["自标错因", "%d/%d" % (sum(1 for q in questions if q.get("error_tags")), len(questions))],
    ]))

    sec("怎么下钻")
    L.append(
        "- 逐题：`questions.jsonl`，一行一题；用 `question_id` 唯一，`attempt_id` 关联同一次练习。\n"
        "- 原文：`passages.jsonl`，`sentences[].i` 与题目里的 `evidence.central_sentences[].index` 同源。\n"
        "- 题组：`groups.jsonl`，填空题的笔记/表格原文在 `body` / `table`，题干本身可能只有占位符。\n"
        "- 写作：`writing.jsonl`，三模型评分在 `scoring.models`，分歧看 `scoring.consensus.band_spread`。\n"
        "- 只想要「做过什么」：`catalog.jsonl` 的 `done` 字段，比 attempts 更全（含未做的篇目）。\n"
    )
    return "\n".join(L)


def build_prompt(meta) -> str:
    c = meta.get("counts", {})
    return """# 雅思练习数据 · 分析指令

你拿到的是同一账号在 idictation.cn 上的练习数据，已归一化为 schema v{ver}。
数据规模：练习 {att} 次、题目 {q} 道、原文/转写 {p} 篇、写作 {w} 篇。

## 读取顺序（别一次性塞满上下文）

1. 先读 `summary.md` 建立全局：分科、分题型、分位置、错题清单。
2. 按需 grep `questions.jsonl`，例如只取某本书：
   `grep '"book": "剑雅18"' questions.jsonl`
3. 需要原文时，按 `passage_id` 去 `passages.jsonl` 取，不要整份加载。
4. 写作单独读 `writing.jsonl`。

## 字段口径（容易误读的地方）

- `state`: `correct` / `wrong` / `blank`（交卷但空着）/ `unattempted`（没做过）。
  **不要把 blank 与 wrong 混为一谈**：前者是时间/策略问题，后者是能力问题。
- `is_correct` 为 `null` 表示没有作答记录，不是「错」。
- `accuracy` 统一为 0–1；站点原值（0–100）保留在 `accuracy_raw`。
- `q_number` 可能是小数（如 23.1），排序请用数值而非字符串。
- 听力判分为本地复算（大小写/冠词/数字写法宽容），与站点可能有 ±1 题差异。
- `evidence.central_sentences[].index` 指向 `passages.jsonl` 同一篇的 `sentences[].i`。

## 输出结构

1. **能力画像**：分题型正确率，标出样本量 < 10 的不要下结论。
2. **失分归因**：把错题分成「定位失败 / 同义替换没认出 / 词义或拼写 / 逻辑判断 / 时间不够」，
   每类给 2–3 个 `question_id` 作为证据。
3. **位置与套书差异**：P1/P2/P3、各套书之间是否有系统性差异。
4. **趋势**：按 `submitted_at` 排序看正确率与用时；样本足够时给出相关系数。
5. **下一步处方**：按「收益/成本」排序，最多 3 条，每条给出可验证的完成标准。

## 禁止

- 不要为凑结论而忽略样本量；n<5 的题型只描述不推论。
- 不要把「平台没有的数据」（单题用时、作答轨迹）说成「你没做」。
""".format(ver=meta.get("schema_version"), att=c.get("attempts", 0),
           q=c.get("questions", 0), p=c.get("passages", 0), w=c.get("writing", 0))
