#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 idictation 原始响应归一化为稳定 schema（v1）。

设计原则
--------
1. **只做映射，不做裁剪**：所有站点字段都能在输出里找到落点；放不下的进 `extra`，
   需要逐字节复现时加 `--keep-raw`。
2. **ID 可重建**：`module:part_id[:result_id]`，同一份数据重复导出 ID 不变，
   方便跨设备合并、跨版本对比。
3. **不依赖中文题干**：题型判定走指令文本特征 + 原始 type 码，换语言/换平台也能用。
4. **缺失即 null，不猜**：拿不到就是 null；`state` 明确区分
   `correct / wrong / blank / unattempted`，避免把「没做」算成「做错」。

字段字典见 `schema/field-dictionary.md`。
"""

from __future__ import annotations

import difflib
import html
import json
import math
import re

SCHEMA_VERSION = "1.0"

# ------------------------------------------------------------------ 基础工具


def clean(s) -> str:
    """去 HTML 标签、解码实体、压缩空白。"""
    if s is None:
        return ""
    s = re.sub(r"<br\s*/?>", " ", str(s), flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def as_list(x) -> list:
    """站点有些字段是 JSON 字符串、有些是数组，统一成 list。"""
    if x is None or x == "":
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, str):
        try:
            v = json.loads(x)
            return v if isinstance(v, list) else [v]
        except json.JSONDecodeError:
            return []
    return [x]


def num(v):
    """题号排序键：'23.1' -> 23.1，'Q14' -> 14，取不到给 inf。"""
    if v is None:
        return math.inf
    m = re.search(r"\d+(?:\.\d+)?", str(v))
    return float(m.group()) if m else math.inf


def part_index(title: str, module: str):
    """Passage 2 / Part 3 -> 2 / 3。"""
    m = re.search(r"(?:Passage|Part|Section)\s*(\d+)", title or "", re.I)
    return int(m.group(1)) if m else None


def hhmmss(sec):
    if sec is None:
        return None
    sec = int(sec)
    return "%d:%02d" % (sec // 60, sec % 60)


# ------------------------------------------------------------------ 题型分类
# 顺序即优先级：越具体的指令越先匹配。
_RULES = (
    ("matching_paragraph", "段落信息匹配", (
        r"which (?:paragraph|section) contains", r"which paragraph",
        r"has seven sections", r"which section contains")),
    ("matching_heading", "标题匹配", (
        r"correct heading", r"list of headings", r"choose the correct heading")),
    ("matching_sentence_ending", "句子结尾匹配", (
        r"correct ending", r"complete each sentence with the correct ending")),
    ("matching_feature", "人物/特征匹配", (
        r"list of (?:researchers|people|scientists|options)", r"match each statement with the correct",
        r"match each .* with the correct (?:person|researcher|writer|expert)",
        r"which (?:researcher|writer|expert|person)")),
    ("tfng", "判断题(T/F/NG)", (r"\btrue\b.{0,40}\bfalse\b", r"not given")),
    ("ynng", "判断题(Y/N/NG)", (r"\byes\b.{0,40}\bno\b", r"not given")),
    ("completion_table", "表格填空", (r"complete the table", r"table below")),
    ("completion_note", "笔记填空", (r"complete the notes", r"notes below")),
    ("completion_form", "表单填空", (r"complete the form", r"form below")),
    ("completion_flowchart", "流程图填空", (r"flow.?chart",)),
    ("completion_summary", "摘要填空", (r"complete the summary", r"summary below",
                                       r"summary of the")),
    ("completion_diagram", "图示填空", (r"label the diagram", r"the diagram below")),
    ("labelling_map", "地图/平面图标注", (r"label the map", r"map below", r"plan below")),
    ("completion_sentence", "句子填空", (r"complete the sentences", r"complete each sentence")),
    ("mcq_multi", "多选", (r"choose (?:two|three|four|five)\b", r"two letters", r"three letters")),
    ("mcq_single", "单选", (r"choose the correct letter", r"choose the correct answer",
                            r"choose one letter")),
    ("matching_other", "其它匹配", (r"\bmatch\b",)),
    ("short_answer", "简答", (r"answer the questions", r"no more than .* words")),
    ("completion_note", "笔记填空", (r"complete the notes",)),
)


def classify(desc: str, type_raw=None, module: str = "reading") -> tuple[str, str]:
    """指令文本 → (type_key, 中文名)。取不到特征时回退 other。"""
    d = clean(desc).lower()
    for key, zh, pats in _RULES:
        for p in pats:
            if re.search(p, d):
                return key, zh
    if "complete" in d:
        return "completion_note", "填空(未细分)"
    if "choose" in d:
        return "mcq_single", "单选"
    return "other", "其它"


def classify_group(group: dict, module: str) -> dict:
    desc = clean(group.get("desc") or group.get("title") or "")
    key, zh = classify(desc, group.get("type"), module)
    return {"question_type": key, "question_type_zh": zh,
            "question_type_raw": group.get("type"), "instruction": desc}


# ------------------------------------------------------------------ 题干解析
def split_stems(group: dict) -> dict:
    """返回 {qid: {"stem":..., "source": "title|collect|table|empty"}}。

    三种存法（平台历史原因，必须都兜住）：
      * 判断/选择题 -> list[].title
      * 填空/笔记题 -> collect 里的 `$N$` 占位符
      * 表格题     -> table.content 二维单元格里的 `$N$` 占位符
    `$N$` 多数是全局题目 id，老数据可能是组内序号，用 resolve() 兜底换算。
    """
    out, qlist = {}, group.get("list") or []
    ids = [q.get("id") for q in qlist if q.get("id") is not None]
    idset = set(ids)

    def resolve(n: int):
        if n in idset:
            return n
        return ids[n - 1] if 1 <= n <= len(ids) else None

    for q in qlist:                                            # 1) title
        t = clean(q.get("title"))
        if t and q.get("id") is not None:
            out[q["id"]] = {"stem": t, "source": "title"}

    collect = group.get("collect") or ""                        # 2) collect
    if isinstance(collect, str) and "$" in collect:
        seg = re.split(r"\$(\d+)\$", collect)
        texts, nums = seg[0::2], seg[1::2]
        for k, raw in enumerate(nums):
            qid = resolve(int(raw))
            if qid is None or qid in out:
                continue
            before = clean(texts[k] if k < len(texts) else "")
            after = clean(texts[k + 1] if k + 1 < len(texts) else "")
            sentence = re.split(r"(?<=[.!?])\s+", before)[-1] if before else ""
            tail = re.split(r"(?<=[.!?])\s+", after)[0] if after else ""
            out[qid] = {"stem": (sentence[-220:] + " ______ " + tail[:100]).strip(),
                        "source": "collect"}

    tb = group.get("table")                                     # 3) table
    if isinstance(tb, dict):
        rows = tb.get("content") or []
        # 有的表格没有表头行（第一行就是数据），不能一律当表头吃掉
        head_is_data = any("$" in str(c or "") for c in (rows[0] if rows else []))
        header = [] if head_is_data else (rows[0] if rows else [])
        start = 0 if head_is_data else 1
        for r in range(start, len(rows)):
            row = rows[r] or []
            label = clean(row[0]) if row else ""
            for c in range(len(row)):                           # 含第 0 列：表头占位也在这一列
                cell = str(row[c] or "")
                for raw in re.findall(r"\$(\d+)\$", cell):
                    qid = resolve(int(raw))
                    if qid is None or qid in out:
                        continue
                    body = clean(cell.replace("$%s$" % raw, " ______ "))
                    col = clean(header[c]) if c < len(header) else ""
                    parts = [col] if (col and c != 0) else []
                    if label and c != 0:
                        parts.append(label)
                    parts.append(body)
                    out[qid] = {"stem": " | ".join(x for x in parts if x)[:280],
                                "source": "table"}

    # 4) 多选题等：题干在组标题里，个别题目没有自己的 title
    group_title = clean(group.get("title"))
    if group_title:
        for q in qlist:
            qid = q.get("id")
            if qid is not None and qid not in out:
                out[qid] = {"stem": group_title, "source": "group_title"}
    return out


# ------------------------------------------------------------------ 阅读
def _reading_paragraphs(v: dict) -> tuple[list[dict], str, str]:
    """返回 (段落, 导语, 来源)。

    少数篇目（实测剑雅21 Test2 P3）站点只给了逐句 `new_content`，`content.A-Z` 全空。
    这时不伪造段落，标记 `paragraph_source="sentences_only"`，让下游知道
    「段落信息匹配」类题目无法靠段落标签核对。
    """
    content = v.get("content") or {}
    order = content.get("order_ary")
    if not isinstance(order, list) or not order:
        order = [k for k in content if len(k) == 1 and k.isalpha()]
    paras = []
    for k in order:
        if not isinstance(k, str):
            continue
        txt = content.get(k)
        if isinstance(txt, str) and txt.strip():
            paras.append({"label": k, "text": clean(txt)})
    if not paras:  # order_ary 缺失时按字母序兜底
        for k in sorted(x for x in content if len(x) == 1 and x.isalpha()):
            if isinstance(content[k], str) and content[k].strip():
                paras.append({"label": k, "text": clean(content[k])})
    lead = clean(content.get("pre-A") or "")
    if paras:
        source = "content"
    elif v.get("new_content"):
        source = "sentences_only"
    else:
        source = "empty"
    return paras, lead, source


def _map_sentence_paragraphs(sentences: list[dict], paras: list[dict]) -> list[dict]:
    """按文本顺序把句子落回段落，避免依赖站点未填的 paragraph 字段。"""
    if not paras:
        return sentences
    bounds, acc = [], 0
    parts = []
    for p in paras:
        start = acc
        parts.append(p["text"])
        acc += len(p["text"]) + 1
        bounds.append((start, acc - 1, p["label"]))
    joined = "\n".join(parts)

    cursor = 0
    last = ""
    for s in sentences:
        t = (s.get("text") or "")[:80]
        idx = joined.find(t, max(0, cursor - 30)) if t else -1
        if idx < 0 and t:
            idx = joined.find(t)
        if idx >= 0:
            cursor = idx + len(t)
            for a, b, label in bounds:
                if a <= idx <= b:
                    s["paragraph"] = label
                    break
        if not s.get("paragraph"):
            # 导语/未收录句：贴到相邻段落，避免空标签破坏排序
            s["paragraph"] = last or (bounds[0][2] if bounds else "")
        last = s.get("paragraph") or last
    return sentences


def _reading_sentences(v: dict, paras: list[dict]) -> list[dict]:
    rows = []
    ga = v.get("grammar_analysis") or []
    for i, s in enumerate(v.get("new_content") or []):
        if not isinstance(s, dict):
            continue
        g = s.get("grammar_analysis")
        if not g and i < len(ga) and isinstance(ga[i], dict):
            g = ga[i].get("grammar_analysis")
        rows.append({
            "i": i,
            "text": (s.get("sentence") or "").strip(),
            "translation": (s.get("translation") or "").strip(),
            "paragraph": "",
            "grammar": g,
            "grammar_html": s.get("grammar_analysis_html") or "",
        })
    return _map_sentence_paragraphs(rows, paras)


def _norm_locating(items) -> list[dict]:
    """locating_words / key_locating_words -> 可读的「定位词→同义替换→原句」。"""
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        pairs = []
        for syn in it.get("syn_ary") or []:
            sents = []
            for t in (syn.get("target_sen") or []):
                if isinstance(t, dict):
                    sents.append({"index": t.get("index"),
                                  "paragraph": t.get("target_para"),
                                  "text": t.get("target_sen") or ""})
            pairs.append({"synonym": syn.get("synonym") or "", "sentences": sents})
        out.append({"locating_word": it.get("locating_word") or "", "synonyms": pairs})
    return out


def _norm_central(items) -> list[dict]:
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        out.append({"index": it.get("index"), "paragraph": it.get("target_para"),
                    "text": it.get("sentence") or "",
                    "translation": it.get("translation") or ""})
    return out


def _norm_ai(ai: dict) -> dict | None:
    if not isinstance(ai, dict) or not ai:
        return None
    return {
        "analysis": ai.get("analysis") or "",
        "reason": ai.get("reason") or "",
        "keywords": ai.get("keywords") or "",
        "paraphrasing": ai.get("paraphrasing") or "",
        "location_sentence": ai.get("location_sentence"),
        "confidence": ai.get("confidence"),
        "sentences": [s.get("sentence") for s in (ai.get("sentences") or [])
                      if isinstance(s, dict) and s.get("sentence")],
    }


def _norm_blocks(blocks) -> list[dict]:
    out = []
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        out.append({"type": b.get("type"), "content": clean(b.get("content")),
                    "location": b.get("location")})
    return out


def _norm_option_analysis(x) -> list[dict]:
    """听力 wrong_reasons 是 {选项字母: 干扰原因}，不是用户自标错因。

    单独放 `evidence.option_analysis`，不要混进 `error_tags`，
    否则统计错因分布时会把「官方干扰项解释」误当成「我做错的原因」。
    """
    if isinstance(x, dict):
        return [{"option": k, "reason": clean(v)} for k, v in x.items()]
    out = []
    for it in x or []:
        if isinstance(it, dict):
            out.append({"option": it.get("option") or it.get("key"),
                        "reason": clean(it.get("reason") or it.get("content"))})
        elif isinstance(it, str) and it.strip():
            out.append({"option": None, "reason": it.strip()})
    return out


def _str_list(x) -> list[str]:
    """把任意 list 压成字符串列表，用于错因标签这类纯文本字段。"""
    out = []
    for v in as_list(x):
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            out.append(str(v.get("name") or v.get("type") or v.get("reason") or ""))
        elif v is not None:
            out.append(str(v))
    return [x for x in out if x]


def _option_list(opt) -> list[dict]:
    out = []
    for o in opt or []:
        if not isinstance(o, dict):
            continue
        out.append({"key": o.get("title") or o.get("key") or "",
                    "text": clean(o.get("content") or o.get("text") or "")})
    return out


def reading_entities(v: dict, item: dict) -> dict:
    """一篇阅读 → {passage, attempt, groups, questions}。"""
    part_id = v.get("paper_id") or item.get("part_id")
    book, test, part = v.get("jianya_name"), v.get("test_name"), v.get("title")
    pr = v.get("practice_result") or {}
    result_id = pr.get("id")
    passage_id = "reading:%s" % part_id
    attempt_id = "reading:%s:%s" % (part_id, result_id) if result_id else None
    paras, lead, para_source = _reading_paragraphs(v)
    sentences = _reading_sentences(v, paras)
    reports = v.get("reports") or {}
    notes_raw = as_list(pr.get("notes"))

    blanks = {}
    for b in as_list(pr.get("result_blanks")):
        if isinstance(b, dict) and b.get("blank_id") is not None:
            blanks[b["blank_id"]] = b

    groups, questions = [], []
    for g in v.get("question") or []:
        gid = g.get("group_id")
        group_id = "reading:%s:%s" % (part_id, gid)
        meta = classify_group(g, "reading")
        qnum = [q.get("number") for q in (g.get("list") or []) if q.get("number") is not None]
        groups.append({
            "schema_version": SCHEMA_VERSION,
            "group_id": group_id,
            "attempt_id": attempt_id,
            "module": "reading",
            "book": book, "test": test, "part": part,
            "part_index": part_index(part, "reading"),
            "question_type": meta["question_type"],
            "question_type_zh": meta["question_type_zh"],
            "question_type_raw": meta["question_type_raw"],
            "instruction": meta["instruction"],
            "title": clean(g.get("title")),
            "body": clean(g.get("collect")),
            "table": g.get("table"),
            "options": _option_list((g.get("collect_option") or {}).get("list")),
            "image_url": g.get("img_url") or None,
            "question_numbers": qnum,
        })

        stems = split_stems(g)
        group_opts = _option_list((g.get("collect_option") or {}).get("list"))
        for q in g.get("list") or []:
            qid = q.get("id")
            if qid is None:
                continue
            b = blanks.get(qid) or {}
            yours = b.get("answer")
            off = b.get("correct_answer") or q.get("display_answer") or ""
            if result_id is None:
                state, is_correct = "unattempted", None
            elif qid in blanks:
                is_correct = bool(b.get("is_correct"))
                state = "correct" if is_correct else ("blank" if not str(yours or "").strip() else "wrong")
            else:
                # 交了卷但这道题没有判定记录：按空答处理，不能算「没做过」
                state, is_correct = "blank", False

            rep = reports.get(str(qid)) or reports.get(qid) or {}
            err_types = as_list(rep.get("types")) if isinstance(rep, dict) else []
            note = next((n.get("content") or n.get("text") for n in notes_raw
                         if isinstance(n, dict) and str(n.get("blank_id")) == str(qid)), "")

            stem = stems.get(qid, {"stem": "", "source": "empty"})
            if not stem["stem"] and group_opts:
                # 极少数多选题没有组标题：用指令当题干，至少能 grep 到
                stem = {"stem": meta["instruction"][:200], "source": "instruction"}
            questions.append({
                "schema_version": SCHEMA_VERSION,
                "question_id": "reading:%s:%s" % (part_id, qid),
                "attempt_id": attempt_id,
                "module": "reading",
                "book": book, "test": test, "part": part,
                "part_index": part_index(part, "reading"),
                "group_id": group_id,
                "question_type": meta["question_type"],
                "question_type_zh": meta["question_type_zh"],
                "question_type_raw": meta["question_type_raw"],
                "q_number": q.get("number"),
                "q_number_raw": str(q.get("number") if q.get("number") is not None else qid),
                "stem": stem["stem"],
                "stem_source": stem["source"],
                "options": _option_list(q.get("option")) or group_opts,
                "yours": yours,
                "correct_answer": off,
                "accepted_answers": q.get("answers") or ([off] if off else []),
                "is_correct": is_correct,
                "state": state,
                "error_tags": _str_list(err_types),
                "error_note": rep.get("description") if isinstance(rep, dict) else None,
                "note": note,
                "evidence": {
                    "locating": _norm_locating(q.get("locating_words")),
                    "key_locating": _norm_locating(q.get("key_locating_words")),
                    "central_sentences": _norm_central(q.get("central_sentences")),
                    "answer_sentences": q.get("answer_sentences") or [],
                    "ai": _norm_ai(q.get("ai_central_sentences")),
                    "ai_analysis": clean(q.get("ai_analyze")),
                    "analysis_blocks": _norm_blocks(q.get("analyze")),
                },
                "extra": {k: q.get(k) for k in ("is_multiple", "sub_essay_code", "wrong_reasons")
                          if q.get(k) not in (None, "", [], {})} or None,
            })

    passage = {
        "schema_version": SCHEMA_VERSION,
        "passage_id": passage_id,
        "module": "reading",
        "book": book, "test": test, "part": part,
        "part_index": part_index(part, "reading"),
        "title": clean((v.get("content") or {}).get("title")),
        "lead_in": lead,
        "paragraph_source": para_source,
        "paragraphs": paras,
        "sentences": sentences,
        "word_count": len(" ".join(
            [p["text"] for p in paras] or [s["text"] for s in sentences]).split()),
        "audio": None,
        "extra": {"question_name": v.get("question_name"),
                  "reader_document_id": v.get("reader_document_id"),
                  "sub_title": clean((v.get("content") or {}).get("sub_title")),
                  "image": (v.get("content") or {}).get("image") or None,
                  "content_notes": (v.get("content") or {}).get("notes") or None} or None,
    }

    total = len(questions)
    correct = sum(1 for q in questions if q["is_correct"])
    blank = sum(1 for q in questions if q["state"] == "blank")
    answered = sum(1 for q in questions if q["state"] in ("correct", "wrong"))
    attempt = None
    if result_id:
        by_type = _by_type(questions)
        attempt = {
            "schema_version": SCHEMA_VERSION,
            "attempt_id": attempt_id,
            "module": "reading",
            "book": book, "test": test, "part": part,
            "part_index": part_index(part, "reading"),
            "passage_id": passage_id,
            "result_id": result_id,
            "user_id": pr.get("user_id"),
            "title": passage["title"],
            "submitted_at": pr.get("created_at"),
            "duration_sec": pr.get("duration"),
            "duration_text": hhmmss(pr.get("duration")),
            "accuracy": _acc(pr.get("zhengquelv"), correct, total),
            "accuracy_raw": pr.get("zhengquelv"),
            "correct": correct, "wrong": answered - correct, "blank": blank,
            "total": total, "answered": answered,
            "action": pr.get("action"),
            "question_range": v.get("question_name"),
            "question_types": _uniq([q["question_type_zh"] for q in questions]),
            "topics": (item.get("topics") or None),
            "by_type": by_type,
            "marks": _marks(pr, paras, questions),
            "vocab_stats": None,
            "history": _history(v, result_id),
        }
    return {"passage": passage, "attempt": attempt, "groups": groups, "questions": questions}


def _marks(pr: dict, paras: list[dict], questions: list[dict]) -> dict:
    """高亮 + 笔记：高亮还原到「第几段第几个字符」，并尽量挂到题号。"""
    order = [p["label"] for p in paras]
    starts, acc = {}, 0
    for p in paras:
        starts[p["label"]] = acc
        acc += len(p["text"]) + 1
    full = "\n".join(p["text"] for p in paras)

    highlights = []
    for h in sorted(as_list(pr.get("highlights")), key=lambda x: x.get("start") or 0):
        text = (h.get("text") or "").strip()
        if not text:
            continue
        pos = full.find(text)
        item = {"text": text, "level": h.get("level"), "scope": h.get("scope_key"),
                "paragraph": None, "char": None, "question_number": None,
                "before": None, "after": None}
        if pos >= 0:
            label = next((k for k in reversed(order) if starts.get(k, 0) <= pos), order[0] if order else None)
            item["paragraph"] = label
            if label:
                j = pos - starts[label]
                p = next(x["text"] for x in paras if x["label"] == label)
                item["char"] = j
                item["before"] = p[max(0, j - 30):j]
                item["after"] = p[j + len(text):j + len(text) + 30]
        else:
            for q in questions:
                if text and text.lower() in (q["stem"] or "").lower():
                    item["question_number"] = q["q_number"]
                    break
        highlights.append(item)

    notes = []
    for n in as_list(pr.get("notes")):
        if isinstance(n, dict):
            notes.append({"content": n.get("content") or n.get("text") or "",
                          "question_number": n.get("blank_id"),
                          "created_at": n.get("created_at")})
    return {"highlights": highlights, "notes": notes,
            "highlight_count": len(highlights)}


def _history(v: dict, current_result_id) -> list[dict]:
    out = []
    grouped = v.get("practice_result_history_grouped") or {}
    for scope, rows in (grouped.items() if isinstance(grouped, dict) else []):
        for r in rows or []:
            res = r.get("result") or {}
            out.append({"scope": scope, "result_id": res.get("id"),
                        "correct": res.get("correct_count") or res.get("zhengquegeshu"),
                        "total": res.get("question_count"), "accuracy": res.get("zhengquelv"),
                        "label": r.get("name"), "submitted_at": r.get("submitted_at"),
                        "is_current": r.get("is_current")})
    if not out:
        for r in v.get("practice_result_history") or []:
            res = r.get("result") or {}
            out.append({"scope": "part", "result_id": res.get("id"),
                        "correct": res.get("correct_count"), "total": res.get("question_count"),
                        "accuracy": res.get("zhengquelv"), "label": r.get("name"),
                        "submitted_at": r.get("submitted_at"), "is_current": r.get("is_current")})
    return out


def _uniq(seq) -> list:
    seen, out = set(), []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _acc(raw, correct, total):
    """站点 zhengquelv 是 0-100 整数；输出统一 0-1。"""
    if isinstance(raw, (int, float)) and raw is not None:
        return round(float(raw) / 100.0, 4)
    return round(correct / total, 4) if total else None


def _by_type(questions: list[dict]) -> list[dict]:
    bucket = {}
    for q in questions:
        if q["is_correct"] is None:
            continue
        b = bucket.setdefault(q["question_type"], {"question_type": q["question_type"],
                                                  "question_type_zh": q["question_type_zh"],
                                                  "correct": 0, "total": 0})
        b["total"] += 1
        b["correct"] += 1 if q["is_correct"] else 0
    for b in bucket.values():
        b["accuracy"] = round(b["correct"] / b["total"], 4) if b["total"] else None
    return sorted(bucket.values(), key=lambda x: -x["total"])


# ------------------------------------------------------------------ 听力
_NUM_WORDS = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
              7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
              13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen",
              17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
              30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy",
              80: "eighty", 90: "ninety", 100: "hundred"}


def norm_answer(s) -> str:
    s = (s or "").lower().strip()
    s = s.replace("’", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[.,;:!?\"()\[\]{}]", " ", s)
    if " " in s:
        s = re.sub(r"\b(a|an|the)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _answer_variants(s) -> set:
    """一个答案的所有可接受写法：原文 + 数字/英文数字互转。"""
    n = norm_answer(s)
    if not n or n == "-":
        return set()
    out = {n}
    if re.fullmatch(r"\d+", n) and int(n) in _NUM_WORDS:
        out.add(_NUM_WORDS[int(n)])
    rev = {v: str(k) for k, v in _NUM_WORDS.items()}
    if n in rev:
        out.add(rev[n])
    return out


def judge(yours, official) -> bool:
    """听力判分：大小写/冠词/标点/数字写法宽容，拼写错误仍算错（与站点口径一致）。"""
    ys = _answer_variants(yours)
    if not ys:
        return False
    alts = set()
    for part in re.split(r"\s*[/;]\s*", official or ""):
        alts |= _answer_variants(part)
    return bool(alts & ys)


def _key(s: str) -> str:
    s = re.sub(r"^[A-Z][A-Za-z'’.\s]{0,20}:\s*", "", (s or "").strip())
    s = re.sub(r"[^a-z0-9 ]", "", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def listening_entities(v: dict, items: list[dict]) -> dict:
    """一个 Test（4 个 Part）→ passages / groups / questions / attempts。

    听力的作答记录（practice_result.answer）挂在目录页的**每个 Part** 上，
    所以「一次提交」= 一个 Part，而不是整卷；attempt 也按 Part 拆分。
    """
    items = items or []
    test_id = v.get("test_id") or (items[0].get("test_id") if items else None)
    book, test = v.get("jianya_name"), v.get("test_name")
    by_pid = {str(it.get("part_id")): it for it in items}

    passages, groups, questions, attempts = [], [], [], []
    for p in v.get("parts") or []:
        pid = p.get("paper_id")
        item = by_pid.get(str(pid)) or {}
        raw_answers = as_list(item.get("raw_answer"))
        answers = {a.get("id"): a for a in raw_answers
                   if isinstance(a, dict) and a.get("id")}
        group_answers = {a.get("group_id"): a for a in raw_answers
                         if isinstance(a, dict) and not a.get("id")}
        part = p.get("title")
        pidx = part_index(part, "listening")
        passage_id = "listening:%s" % pid
        result_id, submitted_at = _part_result(v, pid)
        done = bool(item.get("done") or answers)
        attempt_id = ("listening:%s:%s" % (pid, result_id or "latest")) if done else None
        start = len(questions)

        sentences = _listening_sentences(p)
        passages.append({
            "schema_version": SCHEMA_VERSION,
            "passage_id": passage_id,
            "module": "listening",
            "book": book, "test": test, "part": part,
            "part_index": pidx,
            "title": None,
            "lead_in": "",
            "paragraph_source": "transcript",
            "paragraphs": [],
            "sentences": sentences,
            "word_count": len(re.sub(r"\s+", " ", " ".join(s["text"] for s in sentences)).split()),
            "audio": {"part_url": p.get("file_url"), "full_url": p.get("full_audio")},
            "extra": {"check_interval": p.get("check_interval")} or None,
        })

        for g in p.get("question") or []:
            meta = classify_group(g, "listening")
            group_id = "listening:%s:%s" % (pid, g.get("group_id"))
            groups.append({
                "schema_version": SCHEMA_VERSION,
                "group_id": group_id,
                "attempt_id": attempt_id,
                "module": "listening",
                "book": book, "test": test, "part": part,
                "part_index": pidx,
                "question_type": meta["question_type"],
                "question_type_zh": meta["question_type_zh"],
                "question_type_raw": meta["question_type_raw"],
                "instruction": meta["instruction"],
                "title": clean(g.get("title")),
                "body": clean(g.get("collect")),
                "table": g.get("table"),
                "options": _option_list((g.get("collect_option") or {}).get("list")),
                "image_url": g.get("img_url") or None,
                "question_numbers": [q.get("number") for q in (g.get("list") or [])],
            })

            stems = split_stems(g)
            group_opts = _option_list((g.get("collect_option") or {}).get("list"))
            multi = group_answers.get(g.get("group_id"))
            multi_yours = multi.get("answer") if multi else None
            multi_list = [str(x).strip() for x in multi_yours] if isinstance(multi_yours, list) else []
            for q in g.get("list") or []:
                qid = q.get("id")
                if qid is None:
                    continue
                a = answers.get(qid)
                yours = (a or {}).get("answer")
                off = q.get("display_answer") or (a or {}).get("correct_answer") or ""
                if not done:
                    state, is_correct = "unattempted", None
                elif multi_list:
                    # 「Choose TWO/THREE letters」整组只有一条作答记录（id=0），组内共用一个判定
                    yours = ", ".join(multi_list)
                    corr = {x for x in re.split(r"[,\s/]+", off) if x}
                    is_correct = set(multi_list) == corr
                    state = "correct" if is_correct else "wrong"
                elif a is None:
                    state, is_correct = "blank", False
                elif not str(yours or "").strip():
                    state, is_correct = "blank", False
                else:
                    is_correct = judge(yours, off)
                    state = "correct" if is_correct else "wrong"
                stem = stems.get(qid, {"stem": "", "source": "empty"})
                if not stem["stem"] and group_opts:
                    stem = {"stem": meta["instruction"][:200], "source": "instruction"}
                questions.append({
                    "schema_version": SCHEMA_VERSION,
                    "question_id": "listening:%s:%s" % (pid, qid),
                    "attempt_id": attempt_id,
                    "module": "listening",
                    "book": book, "test": test, "part": part,
                    "part_index": pidx,
                    "group_id": group_id,
                    "question_type": meta["question_type"],
                    "question_type_zh": meta["question_type_zh"],
                    "question_type_raw": meta["question_type_raw"],
                    "q_number": q.get("number"),
                    "q_number_raw": str(q.get("number") if q.get("number") is not None else qid),
                    "stem": stem["stem"],
                    "stem_source": stem["source"],
                    "options": _option_list(q.get("option")) or group_opts,
                    "yours": yours,
                    "correct_answer": off,
                    "accepted_answers": [x for x in re.split(r"\s*[/;]\s*", off) if x],
                    "is_correct": is_correct,
                    "state": state,
                    "error_tags": [],
                    "error_note": None,
                    "note": "",
                    "evidence": {
                        "locating": _norm_locating(q.get("locating_words")),
                        "key_locating": _norm_locating(q.get("key_locating_words")),
                        "central_sentences": _norm_central(q.get("central_sentences")),
                        "answer_sentences": q.get("answer_sentences") or [],
                        "ai": _norm_ai(q.get("ai_central_sentences")),
                        "ai_analysis": clean(q.get("ai_analyze")),
                        "analysis_blocks": _norm_blocks(q.get("analyze")),
                        "option_analysis": _norm_option_analysis(q.get("wrong_reasons")),
                        "start_ms": q.get("start_time"),
                        "end_ms": q.get("end_time"),
                    },
                    "extra": None,
                })

        if not attempt_id:
            continue
        part_qs = questions[start:]
        total = len(part_qs)
        correct = sum(1 for q in part_qs if q["is_correct"])
        blank = sum(1 for q in part_qs if q["state"] == "blank")
        answered = sum(1 for q in part_qs if q["state"] in ("correct", "wrong"))
        duration = item.get("duration_sec")
        attempts.append({
            "schema_version": SCHEMA_VERSION,
            "attempt_id": attempt_id,
            "module": "listening",
            "book": book, "test": test, "part": part,
            "part_index": pidx,
            "passage_id": passage_id,
            "result_id": result_id,
            "title": "%s %s" % (book or "", test or ""),
            "submitted_at": submitted_at or item.get("submitted_at"),
            "duration_sec": duration,
            "duration_text": hhmmss(duration),
            "accuracy": _acc(item.get("accuracy"), correct, total),
            "accuracy_raw": item.get("accuracy"),
            "correct": correct, "wrong": answered - correct, "blank": blank,
            "total": total, "answered": answered,
            "action": None,
            "question_range": item.get("question_range"),
            "question_types": _uniq([q["question_type_zh"] for q in part_qs]),
            "topics": (item.get("topics") or None),
            "by_type": _by_type(part_qs),
            "marks": {"highlights": [], "notes": [], "highlight_count": 0},
            "vocab_stats": _vocab(v),
            "history": _history(v, result_id),
        })
    return {"passages": passages, "attempts": attempts,
            "groups": groups, "questions": questions}


def _part_result(v: dict, pid):
    """该 Part 当前这次提交的 (result_id, submitted_at)。"""
    grouped = v.get("practice_result_history_grouped") or {}
    if not isinstance(grouped, dict):
        return None, None
    fallback = (None, None)
    for _scope, rows in grouped.items():
        for r in rows or []:
            if str(r.get("part_id")) != str(pid):
                continue
            res = r.get("result") or {}
            if r.get("is_current"):
                return res.get("id"), r.get("submitted_at")
            if fallback[0] is None:
                fallback = (res.get("id"), r.get("submitted_at"))
    return fallback


def _listening_sentences(part: dict) -> list[dict]:
    """content（英文+时间轴）与 content_jingting（语法+翻译）序列对齐。"""
    beat = [x for x in (part.get("content") or []) if isinstance(x, dict) and (x.get("en_text") or "").strip()]
    cj = [x for x in (part.get("content_jingting") or []) if isinstance(x, dict) and (x.get("content") or "").strip()]
    col = {}
    sm = difflib.SequenceMatcher(None, [_key(x.get("content")) for x in cj],
                                 [_key(x.get("en_text")) for x in beat], autojunk=False)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            col[b + k] = cj[a + k]

    out = []
    for i, seg in enumerate(beat):
        mate = col.get(i) or {}
        out.append({
            "i": i,
            "text": (seg.get("en_text") or "").strip(),
            "translation": (seg.get("cn_text") or mate.get("translate") or "").strip(),
            "paragraph": part.get("title"),
            "start_ms": seg.get("start_time"),
            "end_ms": seg.get("end_time"),
            "grammar": mate.get("grammar_analysis"),
        })
    return out


def _vocab(v: dict) -> dict | None:
    b = v.get("blank_answer_word_comparison") or {}
    if not isinstance(b, dict) or not b:
        return None
    return {
        "current_accuracy": b.get("current_blank_accuracy_rate"),
        "target_band": b.get("target_ielts_listening_score"),
        "target_accuracy": b.get("target_blank_avg_accuracy_rate"),
        "wrong_word_books": b.get("wrong_answer_word_books") or [],
        "noticed": b.get("noticed"),
    }


# ------------------------------------------------------------------ 写作
_DIM_ZH = {"task_performance": "任务回应", "coherence_and_cohesion": "连贯与衔接",
           "lexical_resource": "词汇资源", "grammatical_range": "语法多样性与准确性"}
_MODELS = ("qwen", "deepseek", "doubao")


def writing_entity(r: dict) -> dict:
    kind = "dazuowen" if (r.get("dazuowen_paper_id") or 0) else "xiaozuowen"
    paper = r.get("%s_paper" % kind) or {}
    task = "task_2" if kind == "dazuowen" else "task_1"

    models, bands, dim_acc = {}, [], {}
    for m in _MODELS:
        d = r.get("%s_%s_score_details" % (kind, m))
        if not isinstance(d, dict) or not d:
            continue
        dims = []
        for dim in d.get("dimensions") or []:
            key = dim.get("key")
            items = [{"name": it.get("name"), "score": it.get("score"),
                      "reason": it.get("reason")} for it in (dim.get("items") or [])]
            dims.append({"key": key, "name": dim.get("name") or _DIM_ZH.get(key, ""),
                         "en_name": dim.get("en_name"), "score": dim.get("score"),
                         "reason": dim.get("reason"), "items": items})
            if isinstance(dim.get("score"), (int, float)):
                dim_acc.setdefault(key, []).append(dim["score"])
        models[m] = {"band": d.get("band_score"), "raw_band": d.get("raw_band_score"),
                     "intervention": d.get("score_intervention"),
                     "task_type": d.get("task_type"), "dimensions": dims}
        if isinstance(d.get("band_score"), (int, float)):
            bands.append(d["band_score"])

    consensus = None
    if bands:
        consensus = {
            "band_mean": round(sum(bands) / len(bands), 2),
            "band_min": min(bands), "band_max": max(bands),
            "band_spread": round(max(bands) - min(bands), 2),
            "models_counted": len(bands),
            "by_dimension": {k: round(sum(v) / len(v), 2) for k, v in dim_acc.items() if v},
        }

    corr = r.get("corrections") or {}
    essays = r.get("sample_essay") or {}
    history = []
    for h in r.get("practice_result_history") or []:
        res = h.get("result") or {}
        history.append({"result_id": res.get("id"), "label": h.get("name"),
                        "submitted_at": h.get("submitted_at"), "is_current": h.get("is_current")})
    for h in (paper.get("practice_result_history") or []):
        res = h.get("result") or {}
        history.append({"result_id": res.get("id"), "label": h.get("name"),
                        "submitted_at": h.get("submitted_at"), "is_current": h.get("is_current")})

    return {
        "schema_version": SCHEMA_VERSION,
        "writing_id": "writing:%s" % r.get("id"),
        "attempt_id": "writing:%s" % r.get("id"),
        "module": "writing",
        "task": task,
        "kind": kind,
        "kind_zh": "大作文" if kind == "dazuowen" else "小作文",
        "source": r.get("source"),
        "book": _book_of(paper.get("name") or r.get("paper_name")),
        "test": None,
        "paper_name": paper.get("name") or r.get("paper_name"),
        "paper_id": r.get("%s_paper_id" % kind),
        "question": {
            "text": clean(paper.get("content")),
            "category": paper.get("content_category"),
            "image_url": paper.get("img_url") or None,
            "image_desc": clean(paper.get("img_desc")) or None,
        },
        "essay": {
            "text": r.get("%s_content" % kind) or "",
            "word_count": r.get("%s_word_count" % kind),
            "duration_sec": r.get("duration"),
            "duration_text": hhmmss(r.get("duration")),
            "submitted_at": r.get("created_at"),
        },
        "scoring": {
            "total_score": r.get("total_score"),
            "score": r.get("score"),
            "corrected_at": r.get("corrected_at"),
            "models": models,
            "consensus": consensus,
        },
        "corrections": corr.get(kind) or [],
        "corrections_done": bool(corr.get("%s_done" % kind)),
        "sample_essay": {"title": (essays.get(kind) or {}).get("title"),
                         "text": (essays.get(kind) or {}).get("content")} if essays.get(kind) else None,
        "marks": {"highlights": r.get("highlights") or [], "notes": r.get("notes") or [],
                  "result_notes": r.get("result_notes")},
        "history": history,
        "extra": {"step1_done": r.get("step1_done"), "step2_done": r.get("step2_done"),
                  "step3_done": r.get("step3_done")},
    }


def _book_of(name: str) -> str | None:
    m = re.search(r"(剑雅\s*\d+|剑\s*\d+)", name or "")
    return m.group(1).replace(" ", "") if m else None


# ------------------------------------------------------------------ 目录行
def catalog_row(item: dict) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "module": item.get("module"),
        "source": item.get("source"),
        "book": item.get("book"),
        "test": item.get("test"),
        "part": item.get("title"),
        "part_index": part_index(item.get("title") or "", item.get("module") or ""),
        "part_id": item.get("part_id"),
        "test_id": item.get("test_id"),
        "done": bool(item.get("done")),
        "accuracy": (round(item["accuracy"] / 100.0, 4)
                     if isinstance(item.get("accuracy"), (int, float)) else None),
        "duration_sec": item.get("duration_sec"),
        "question_range": item.get("question_range"),
        "question_types": as_list(item.get("question_types")),
        "topics": as_list(item.get("topics")),
        "total_num": item.get("total_num"),
        "kind": item.get("kind"),
    }
