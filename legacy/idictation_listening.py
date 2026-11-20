"""idictation.cn 听力（剑雅 + 机经）作答数据接口

    from idictation_listening import list_parts, get_detail

    parts = list_parts(cookie)                 # 所有听力 Part + 是否做过
    data  = get_detail(cookie, 2001)           # 某个 Test 的逐题明细（做题才有）

数据来源：
    POST /api/study/zhenti/v1/test/list       剑雅听力 Part 索引 + 我的作答(answer)
    POST /api/study/zhenti/v1/test/show/<id>  该 Test 的官方题目与 display_answer
    POST /api/study/zhenti/v1/jj/list         机经听力 Part 索引

注意：听力没有 result_blanks 那种逐题判定，需要自己拿 display_answer 比对，
      所以本模块内置了 IELTS 听力标准化的宽松判分（大小写/冠词/数字/多答案）。
"""

import difflib
import json
import re
import sys

from IELTS_idictation_api import _post

LIST_URL = "/api/study/zhenti/v1/test/list"
SHOW_URL = "/api/study/zhenti/v1/test/show/"
JJ_URL = "/api/study/zhenti/v1/jj/list"

_NUM = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
        7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
        13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen",
        17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
        30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy",
        80: "eighty", 90: "ninety", 100: "hundred"}


# ---------------------------------------------------------------- 判分
def norm(s) -> str:
    s = (s or "").lower().strip()
    s = s.replace("’", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[.,;:!?\"()\[\]{}]", " ", s)
    if " " in s:                                          # 单词答案不能剔冠词，否则 A 变空
        s = re.sub(r"\b(a|an|the)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if s in ("", "-"):
        return ""
    if re.fullmatch(r"\d+", s) and int(s) in _NUM:       # 10 <-> ten
        return f"{s} {_NUM[int(s)]}"
    return s


def _alts(ans: str) -> set:
    """官方答案可能是 "10 / ten"、"cafe / café" 这类的多写法"""
    out = set()
    for part in re.split(r"\s*[/;]\s*", ans or ""):
        n = norm(part)
        if n:
            out.add(n)
    return out


def judge(yours, official) -> bool:
    """逐题判分。整体比较，不做拆词，口径与站点一致（拼写/空格错即错）。"""
    y = norm(yours)
    if not y:
        return False
    ys = {y}
    if re.fullmatch(r"\d+", y) and int(y) in _NUM:              # 数字 <-> 英文数字
        ys.add(_NUM[int(y)])
    rev = {v: str(k) for k, v in _NUM.items()}
    if y in rev:
        ys.add(rev[y])
    alts = _alts(official)
    return bool(alts & ys)


# ---------------------------------------------------------------- 索引
def list_parts(cookie: str, source: str = "jianya") -> list:
    """所有听力 Part。done=True 时 accuracy/duration_sec 有值。"""
    url = LIST_URL if source == "jianya" else JJ_URL
    raw = _post(url, {"page": 1, "limit": 100}, cookie, timeout=60)

    out = []
    for book in raw.get("books") or []:
        for test in book.get("children") or []:
            for part in test.get("children") or []:
                pr = part.get("practice_result") or {}
                out.append({
                    "book": book.get("name"),
                    "test": test.get("name"),
                    "test_id": test.get("test_id"),
                    "part_id": part.get("id"),
                    "part": part.get("title"),
                    "range": part.get("question"),
                    "question_type": part.get("question_type"),
                    "done": bool(pr),
                    "accuracy": pr.get("zhengquelv"),
                    "correct": pr.get("zhengquegeshu"),
                    "total_num": part.get("total_num"),
                    "duration_sec": pr.get("duration"),
                    "raw_answer": pr.get("answer"),
                })
    return out


# ---------------------------------------------------------------- 明细
_cache = {}


def get_test(cookie: str, test_id) -> dict:
    key = str(test_id)
    if key not in _cache:
        _cache[key] = _post(SHOW_URL + key, {}, cookie, timeout=60)
    return _cache[key]


def _official(v: dict) -> dict:
    """{题目 id: (官方答案, 题型)}，按 Test 维度打平"""
    out = {}
    for part in v.get("parts") or []:
        for g in part.get("question") or []:
            for q in g.get("list") or []:
                if q.get("id") is not None:
                    out[q["id"]] = (q.get("display_answer") or "", g.get("type"))
    return out


def _stems(v: dict) -> dict:
    """{题目 id: 题干}，复用阅读那边的三种解析规则"""
    from IELTS_idictation_api import _parse_stems
    out = {}
    for part in v.get("parts") or []:
        for g in part.get("question") or []:
            out.update(_parse_stems(g))
    return out


def get_detail(cookie: str, test_id, part: str = None) -> dict:
    """某个 Test 的逐题明细。part 传 'Part 1' 之类可只取一个 Part。"""
    v = get_test(cookie, test_id)
    official, stems = _official(v), _stems(v)

    rows = []
    for p in v.get("parts") or []:
        pr_all = p.get("practice_result") or {}
        # part 级作答不在 parts[] 里，退回 test/list 的 raw_answer
        if not pr_all:
            continue
        for a in json.loads(pr_all.get("answer") or "[]"):
            off = official.get(a.get("id"), ("", None))[0]
            rows.append({
                "part": p.get("title"),
                "no": a.get("id"),
                "your_answer": a.get("answer"),
                "correct_answer": off,
                "is_correct": judge(a.get("answer"), off),
                "stem": stems.get(a.get("id"), ""),
            })
    return {"test_id": test_id, "book": v.get("jianya_name"),
            "test": v.get("test_name"), "answers": rows}


def detail_from_index(cookie: str, item: dict) -> dict:
    """用 list_parts() 里的一条，还原逐题明细（听力作答只存在 list 的 practice_result 里）"""
    v = get_test(cookie, item["test_id"])
    official, stems = _official(v), _stems(v)

    # 该 Part 内题目 id 的合法集合（防串到别的 Part）
    part_ids = []
    for p in v.get("parts") or []:
        if p.get("title") == item["part"]:
            for g in p.get("question") or []:
                for q in g.get("list") or []:
                    part_ids.append(q.get("id"))
    order = {qid: i for i, qid in enumerate(part_ids)}

    rows = []
    for a in json.loads(item.get("raw_answer") or "[]"):
        qid = a.get("id")
        if qid not in order:
            continue
        off = official.get(qid, ("", None))[0]
        rows.append({
            "idx": order[qid],
            "no": qid,
            "your_answer": a.get("answer"),
            "correct_answer": off,
            "is_correct": judge(a.get("answer"), off),
            "stem": stems.get(qid, ""),
        })
    rows.sort(key=lambda r: r["idx"])
    return rows


# ---------------------------------------------------------------- 听力原文 / 提交历史
def _key(s: str) -> str:
    """对齐用的文本指纹：去掉 WOMAN:/MAN: 之类说话人前缀、大小写与标点"""
    s = re.sub(r"^[A-Z][A-Za-z'’.\s]{0,20}:\s*", "", (s or "").strip())
    s = re.sub(r"[^a-z0-9 ]", "", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def get_transcript(cookie: str, test_id, part: str = None) -> list:
    """听力原文，分段带时间轴。

    返回 [{part, order, start_ms, end_ms, en, cn, grammar}]
    en/cn 来自 parts[].content（逐句中英对照 + 毫秒时间轴）；grammar 来自
    content_jingting 的 AI 语法分析（主句/时态/成分拆解）。
    两列段数不等且 content 多出「PART 1」等标题行，所以用序列对齐而不是按下标硬对。
    """
    v = get_test(cookie, test_id)
    out = []
    for p in v.get("parts") or []:
        if part and p.get("title") != part:
            continue
        cj = [x for x in (p.get("content_jingting") or []) if (x.get("content") or "").strip()]
        beat = [x for x in (p.get("content") or []) if (x.get("en_text") or "").strip()]
        # beat[i] -> cj[j]
        col = {}
        sm = difflib.SequenceMatcher(None, [_key(x.get("content")) for x in cj],
                                     [_key(x.get("en_text")) for x in beat], autojunk=False)
        for a, b, size in sm.get_matching_blocks():
            for k in range(size):
                col[b + k] = cj[a + k]
        for i, seg in enumerate(beat):
            out.append({
                "part": p.get("title"),
                "order": seg.get("order"),
                "start_ms": seg.get("start_time"),
                "end_ms": seg.get("end_time"),
                "en": (seg.get("en_text") or "").strip(),
                "cn": (seg.get("cn_text") or "").strip(),
                "grammar": (col.get(i) or {}).get("grammar_analysis"),
            })
    return out
    return out


def get_audio(cookie: str, test_id, part: str = None) -> dict:
    """音频直链：full_audio 是整卷，file_url 是单 Part"""
    v = get_test(cookie, test_id)
    out = {}
    for p in v.get("parts") or []:
        if part and p.get("title") != part:
            continue
        out[p.get("title")] = {"part_audio": p.get("file_url"), "full_audio": p.get("full_audio")}
    return out


def list_history(cookie: str, test_id) -> list:
    """该 Test 的提交记录：每次的 result_id / 对几题 / 提交时间（可重复刷）"""
    v = get_test(cookie, test_id)
    out = []
    for key, rows in (v.get("practice_result_history_grouped") or {}).items():
        for r in rows or []:
            res = r.get("result") or {}
            out.append({
                "scope": key,
                "result_id": res.get("id"),
                "correct": res.get("correct_count") or res.get("zhengquegeshu"),
                "total": res.get("question_count"),
                "accuracy": res.get("zhengquelv"),
                "label": r.get("name"),
                "submitted_at": r.get("submitted_at"),
                "is_current": r.get("is_current"),
            })
    if not out:                                    # 兜底：part 级历史
        for r in v.get("practice_result_history_part") or []:
            res = r.get("result") or {}
            out.append({
                "scope": "part", "result_id": res.get("id"),
                "correct": res.get("correct_count"), "total": res.get("question_count"),
                "accuracy": res.get("zhengquelv"), "label": r.get("name"),
                "submitted_at": r.get("submitted_at"),
            })
    return out


if __name__ == "__main__":
    ck = "idictation_session=" + open(r"C:/Users/yyyyy/.workbuddy/.idict_ck").read().strip()
    parts = list_parts(ck)
    for x in parts:
        print(x["book"], x["test"], x["part"], x["accuracy"], x["duration_sec"], x["done"])
