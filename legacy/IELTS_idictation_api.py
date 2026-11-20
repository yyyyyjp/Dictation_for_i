"""idictation.cn 阅读作答数据接口（最小实现）

    from idictation_api import list_parts, get_result

    parts = list_parts(cookie)          # 有哪些文章 + part_id
    data  = get_result(cookie, 17)      # 某一篇的作答明细

底层只有两个 HTTP 接口，签名规则见文件末尾注释，可直接用任何语言复刻。
"""

import hashlib
import hmac
import json
import random
import re
import string
import time
import urllib.parse
import urllib.request

BASE = "https://www.idictation.cn"
SECRET = "idictation_2024"                                    # 前端硬编码签名密钥

API_LIST = "/api/study/yuedu-zhenti/v1/jianya/list"           # 文章列表
API_SHOW = "/api/study/yuedu-zhenti/v1/jianya/part/show/"     # 单篇详情（含作答）
# G 类阅读把 yuedu-zhenti 换成 yuedu-g-zhenti，结构完全一致


# ---------------------------------------------------------------- 底层：签名 + 请求
def _sign(data: dict) -> str:
    parts = []
    for k in sorted(data):
        v = data[k]
        if isinstance(v, (dict, list)):
            v = json.dumps(v, separators=(",", ":"), ensure_ascii=False)
        parts.append(f"{k}={v}")
    return hmac.new(SECRET.encode(), "&".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()


def _post(url: str, payload: dict, cookie: str, timeout: int = 30) -> dict:
    d = {k: v for k, v in payload.items() if v is not None and v != ""}
    d["api_key"] = urllib.parse.quote(url, safe="")
    d["timestamp"] = int(time.time())
    d["nonce"] = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    d["sign"] = _sign(d)

    req = urllib.request.Request(
        BASE + url,
        data=json.dumps(d).encode("utf-8"),
        headers={"Content-Type": "application/json", "Cookie": cookie,
                 "Referer": BASE + "/", "User-Agent": "Mozilla/5.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode("utf-8"))
    if isinstance(body, dict) and body.get("status") == 401:
        raise PermissionError("登录态失效，重新取 idictation_session")
    return body.get("values", body) if isinstance(body, dict) else body


# ---------------------------------------------------------------- 对外：两个函数
def list_parts(cookie: str, source: str = "jianya") -> list:
    """所有文章的索引。每项含 part_id / book / test / passage / done。"""
    path = API_LIST if source == "jianya" else API_LIST.replace("yuedu-zhenti", "yuedu-g-zhenti")
    raw = _post(path, {"page": 1, "limit": 100}, cookie)

    out = []
    for book in raw.get("books") or []:
        for test in book.get("children") or []:
            for part in test.get("children") or []:
                pr = part.get("practice_result") or {}
                out.append({
                    "part_id": part.get("id"),
                    "book": book.get("name"),
                    "test": test.get("name"),
                    "passage": part.get("title"),
                    "done": bool(pr),
                    "accuracy": pr.get("zhengquelv"),
                    "duration_sec": pr.get("duration"),
                })
    return out


def get_result(cookie: str, part_id: int, source: str = "jianya") -> dict:
    """单篇作答明细。判分只取 result_blanks，answer[].mark 不可靠。"""
    path = API_SHOW if source == "jianya" else API_SHOW.replace("yuedu-zhenti", "yuedu-g-zhenti")
    v = _post(path + str(part_id), {}, cookie)
    pr = v.get("practice_result") or {}

    stems, types = {}, {}
    for g in v.get("question") or []:
        for q in g.get("list") or []:
            types[q.get("id")] = g.get("type")
        stems.update(_parse_stems(g))

    blanks = json.loads(pr.get("result_blanks") or "[]")
    answers = [{
        "no": b.get("blank_id"),
        "your_answer": b.get("answer"),
        "correct_answer": b.get("correct_answer"),
        "is_correct": bool(b.get("is_correct")),
        "stem": stems.get(b.get("blank_id"), ""),
        "type": types.get(b.get("blank_id")),
    } for b in blanks]

    return {
        "part_id": part_id,
        "book": v.get("jianya_name"),
        "test": v.get("test_name"),
        "passage": v.get("title"),
        "result_id": pr.get("id"),
        "accuracy": pr.get("zhengquelv"),
        "correct": sum(a["is_correct"] for a in answers),
        "total": len(answers),
        "duration_sec": pr.get("duration"),
        "submitted_at": pr.get("created_at"),
        "answers": answers,
    }


# ---------------------------------------------------------------- 内部：题干解析
def _clean(s) -> str:
    """去标签 + 压缩空白"""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def _parse_stems(group: dict) -> dict:
    """从一个题目组里解析 {题号 id: 题干}。

    三种存法：
      * 判断/选择题 -> list[].title
      * 填空/笔记题 -> collect 里的 $N$ 占位符
      * 表格题      -> table.content 二维单元格里的 $N$ 占位符
    $N$ 通常是全局题号(id)，老数据可能是组内序号，需兜底换算。
    """
    out, qlist = {}, group.get("list") or []
    ids = [q.get("id") for q in qlist if q.get("id") is not None]
    idset = set(ids)

    def resolve(n):
        if n in idset:
            return n
        return ids[n - 1] if 1 <= n <= len(ids) else None

    for q in qlist:                                        # 1) title 优先
        t = _clean(q.get("title"))
        if t and q.get("id") is not None:
            out[q["id"]] = t

    collect = group.get("collect") or ""                    # 2) collect 的 $N$
    if "$" in collect:
        seg = re.split(r"\$(\d+)\$", collect)
        texts, nums = seg[0::2], seg[1::2]
        for k, num in enumerate(nums):
            qid = resolve(int(num))
            if qid is None or qid in out:
                continue
            before = _clean(texts[k] if k < len(texts) else "")
            after = _clean(texts[k + 1] if k + 1 < len(texts) else "")
            sentence = re.split(r"(?<=[.!?])\s+", before)[-1] if before else ""
            tail = re.split(r"(?<=[.!?])\s+", after)[0] if after else ""
            out[qid] = (sentence[-200:] + " ______ " + tail[:80]).strip()

    tb = group.get("table")                                 # 3) 表格单元格
    if isinstance(tb, dict):
        rows = tb.get("content") or []
        header = rows[0] if rows else []
        for r in range(1, len(rows)):
            row = rows[r] or []
            label = _clean(row[0]) if row else ""
            for c in range(1, len(row)):
                cell = row[c] or ""
                for num in re.findall(r"\$(\d+)\$", cell):
                    qid = resolve(int(num))
                    if qid is None or qid in out:
                        continue
                    body = _clean(cell.replace(f"${num}$", " ______ "))
                    col = _clean(header[c]) if c < len(header) else ""
                    out[qid] = " | ".join(x for x in (col, label, body) if x)[:260]
    return out


# ---------------------------------------------------------------- 阅读原文 / 做题标记 / 官方解析
def _as_list(x) -> list:
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            return []
    return x or []


def _parts(v: dict) -> dict:
    """原文段落 {A: 文本}，去掉 title 和空的图片占位键"""
    c = v.get("content") or {}
    return {k: s for k, s in c.items()
            if k.isalpha() and k != "title" and isinstance(s, str) and s.strip()}


def get_passage(cookie: str, part_id: int, source: str = "jianya") -> dict:
    """阅读单篇：原文分段 + 题目 + 官方解析 + 逐题判定。

    比 get_result 多的东西：
      content           {A:'...', B:'...'} 原文段落
      new_content       逐句英文 + 中文 translation
      grammar_analysis  逐句语法（sentence / paragraph / 成分）
      每题 locating_words / key_locating_words（官方定位词+同义替换+原文句）
      每题 central_sentences（中心句+翻译）、ai_analyze（AI 完整解析）
    """
    path = API_SHOW if source == "jianya" else API_SHOW.replace("yuedu-zhenti", "yuedu-g-zhenti")
    v = _post(path + str(part_id), {}, cookie, timeout=60)
    pr = v.get("practice_result") or {}
    blanks = {b.get("blank_id"): b for b in _as_list(pr.get("result_blanks"))}

    qs = []
    for g in v.get("question") or []:
        for q in g.get("list") or []:
            b = blanks.get(q.get("id")) or {}
            qs.append({
                "no": q.get("number") or q.get("id"),
                "id": q.get("id"),
                "stem": _clean(q.get("title")),
                "type": g.get("type"),
                "your_answer": b.get("answer"),
                "correct_answer": b.get("correct_answer") or q.get("display_answer"),
                "is_correct": bool(b.get("is_correct")),
                "locating_words": q.get("locating_words"),
                "key_locating_words": q.get("key_locating_words"),
                "central_sentences": q.get("central_sentences"),
                "ai_analyze": q.get("ai_analyze"),
            })

    return {
        "part_id": part_id,
        "book": v.get("jianya_name"),
        "test": v.get("test_name"),
        "passage": v.get("title"),
        "title": (v.get("content") or {}).get("title"),
        "paragraphs": _parts(v),
        "sentences": v.get("new_content"),
        "grammar": v.get("grammar_analysis"),
        "questions": qs,
        "duration_sec": pr.get("duration"),
        "submitted_at": pr.get("created_at"),
    }


def get_marks(cookie: str, part_id: int, source: str = "jianya", ctx: int = 30) -> dict:
    """做题时留下的标记：高亮 + 笔记。

    高亮分两类（scope_key）：
      article  —— 在原文上高亮，用段落流顺序匹配还原到「第几段第几个字符」
      question —— 在题干/选项上高亮，尽量定位到题号
    level 1 = 主高亮，level 2 = 次高亮；start/end 是整篇（原文+题干）的全局偏移，
    不能直接用，因为原文前面还有约 171 字符的前置内容，且段间有换行。
    """
    path = API_SHOW if source == "jianya" else API_SHOW.replace("yuedu-zhenti", "yuedu-g-zhenti")
    v = _post(path + str(part_id), {}, cookie, timeout=60)
    pr = v.get("practice_result") or {}

    paras = _parts(v)
    order = sorted(paras)
    starts, acc = {}, 0
    for k in order:
        starts[k] = acc
        acc += len(paras[k]) + 1
    full = "\n".join(paras[k] for k in order)

    stems = []                      # 题干流，用于定位 question 高亮
    for g in v.get("question") or []:
        for q in g.get("list") or []:
            t = _clean(q.get("title"))
            if t:
                stems.append((q.get("number") or q.get("id"), t))
    stream = " ".join(t for _, t in stems)
    pos_q = 0

    out = []
    for h in sorted(_as_list(pr.get("highlights")), key=lambda x: x.get("start") or 0):
        text = h.get("text") or ""
        if not text:
            continue
        item = {"text": text, "level": h.get("level"),
                "scope": h.get("scope_key"), "para": None, "question_no": None}

        i = full.find(text)                              # 先当原文高亮
        if i >= 0:
            para = next((k for k in reversed(order) if starts[k] <= i), order[0])
            item["para"] = para
            item["char"] = i - starts[para]
            j = i - starts[para]
            p = paras[para]
            item["before"] = p[max(0, j - ctx):j]
            item["after"] = p[j + len(text):j + len(text) + ctx]
        else:                                            # 再当题干高亮
            j = stream.lower().find(text.lower(), pos_q)
            if j < 0:
                j = stream.lower().find(text.lower())
            if j >= 0:
                pos_q = j
                acc2 = 0
                for no, t in stems:
                    if acc2 + len(t) >= j:
                        item["question_no"] = no
                        break
                    acc2 += len(t) + 1
        out.append(item)

    return {
        "part_id": part_id,
        "passage": v.get("title"),
        "highlights": out,
        "notes": _as_list(pr.get("notes")),
        "counts": {"total": len(out),
                   "article": sum(1 for x in out if x["para"]),
                   "question": sum(1 for x in out if x["question_no"]),
                   "unplaced": sum(1 for x in out if not x["para"] and not x["question_no"])},
    }


if __name__ == "__main__":
    # 自测：python idictation_api.py 17
    import os
    import sys

    ck = os.environ.get("IDICT_COOKIE", "")
    if not ck:
        sys.exit("先设置 IDICT_COOKIE 环境变量")
    print(json.dumps(get_result(ck, int(sys.argv[1]) if len(sys.argv) > 1 else 1),
                     ensure_ascii=False, indent=1))

# ---------------------------------------------------------------- 接口规格
# 两个接口都是 POST，JSON body，鉴权靠 Cookie（只需 idictation_session）。
# 每个请求必须带签名：
#   api_key   = urllib.parse.quote(接口路径, safe="")   # 是路径，不含域名
#   timestamp = 秒级时间戳
#   nonce     = 10 位随机小写字母 + 数字
#   sign      = HMAC-SHA256(密钥 "idictation_2024",
#                           "&".join(f"{k}={v}" for k 升序，排除 sign 本身))
#   数组/对象类型的值先 json.dumps(separators=(",",":"), ensure_ascii=False)
#
# 返回体：{"status":200,"values":{...}}；未登录返回 {"status":401,...}
