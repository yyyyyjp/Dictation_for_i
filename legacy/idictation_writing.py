"""idictation.cn 写作（小作文 Task1 / 大作文 Task2）数据接口

    from idictation_writing import list_papers, list_results, get_result, summarize

    papers  = list_papers(cookie, "dazuowen")        # 题库（剑雅/机经/G类）
    results = list_results(cookie)                   # 我的提交记录（含正文+AI批改）
    one     = get_result(cookie, results[0]["id"])   # 单份完整结果（37 字段）

三个数据模块：
    xiezuo-zhenti    剑雅 A 类真题（大 72 / 小 72，18 本）
    xiezuo-jijing    写作机经  （大 54 / 小 51）
    xiezuo-g-zhenti  剑雅 G 类  （大 54 / 小 54，17 本）

核心发现：批改由 qwen / deepseek / doubao 三个模型各出一份，字段名形如
`dazuowen_qwen_score_details`，每份含 band_score + 四个维度 × 若干检查项（含 reason）。
"""

import json

from IELTS_idictation_api import _post

WORK = "/api/study"
MODULES = {"zhenti": "xiezuo-zhenti", "jijing": "xiezuo-jijing", "g": "xiezuo-g-zhenti"}
MODELS = ("qwen", "deepseek", "doubao")
DIM_CN = {"task_performance": "任务回应", "coherence_and_cohesion": "连贯与衔接",
          "lexical_resource": "词汇资源", "grammatical_range": "语法多样性与准确性"}


def _b(module: str) -> str:
    return f"{WORK}/{MODULES.get(module, module)}/v1"


# ---------------------------------------------------------------- 题库
def list_papers(cookie: str, kind: str = "dazuowen", module: str = "zhenti") -> list:
    """题库索引。kind: dazuowen / xiaozuowen。每项含 paper_id / name / 是否做过。"""
    raw = _post(_b(module) + f"/{kind}/list", {"page": 1, "limit": 100}, cookie, timeout=60)
    out = []
    for book in raw.get("books") or []:
        for test in book.get("children") or []:
            for p in test.get("children") or []:
                out.append({
                    "module": MODULES.get(module, module),
                    "kind": kind,
                    "book": book.get("name"),
                    "test": test.get("name"),
                    "name": p.get("name"),
                    "paper_id": p.get("id") or p.get("paper_id"),
                    "done": bool(p.get("practice_result")),
                    "last_score": p.get("score"),
                })
    return out


# ---------------------------------------------------------------- 提交记录
def list_results(cookie: str, page: int = 1, limit: int = 20, module: str = "zhenti") -> dict:
    """我的写作提交记录（列表页那一份就已经含正文和全部 AI 批改）

    返回 {list, date_filter, kind_filter, type_filter, paper_filter}
    """
    return _post(_b(module) + "/results/list", {"page": page, "limit": limit}, cookie, timeout=60)


def get_result(cookie: str, result_id: int, module: str = "zhenti") -> dict:
    """单份结果，37 个字段。比 list 多 duration / paper 详情 / history"""
    return _post(_b(module) + "/results/show", {"id": result_id}, cookie, timeout=60).get("result") or {}


def error_types(cookie: str, module: str = "zhenti") -> list:
    """可自标的错误类型（作文 6 类）"""
    return (_post(_b(module) + "/errors/all-types", {}, cookie, timeout=30) or {}).get("types") or []


# ---------------------------------------------------------------- 结构化
def summarize(r: dict) -> dict:
    """把一份 result 摊平成好用的结构：题目 / 我的正文 / 三模型分数 / 维度明细 / 批注 / 范文"""
    kind = "dazuowen" if (r.get("dazuowen_paper_id") or 0) else "xiaozuowen"
    paper = r.get(f"{kind}_paper") or {}

    scores = {}
    for m in MODELS:
        d = r.get(f"{kind}_{m}_score_details") or {}
        if not d:
            continue
        scores[m] = {
            "band": d.get("band_score"),
            "raw_band": d.get("raw_band_score"),
            "intervention": d.get("score_intervention"),
            "dims": [{
                "key": dim.get("key"),
                "name": dim.get("name") or DIM_CN.get(dim.get("key"), ""),
                "items": [{"name": it.get("name"), "score": it.get("score"),
                           "reason": it.get("reason")} for it in (dim.get("items") or [])],
            } for dim in (d.get("dimensions") or [])],
        }

    corr = r.get("corrections") or {}
    essays = r.get("sample_essay") or {}
    return {
        "result_id": r.get("id"),
        "kind": kind,
        "paper_name": paper.get("name") or r.get("paper_name"),
        "topic": paper.get("content_category"),
        "question": paper.get("content"),
        "image_url": paper.get("img_url") or None,
        "image_desc": paper.get("img_des") or None,
        "my_essay": r.get(f"{kind}_content"),
        "word_count": r.get(f"{kind}_word_count"),
        "duration_sec": r.get("duration"),
        "submitted_at": r.get("created_at"),
        "corrected_at": r.get("corrected_at"),
        "total_score": r.get("total_score"),
        "scores": scores,
        "corrections": corr.get(kind) or [],
        "corrections_done": bool(corr.get(f"{kind}_done")),
        "sample_essay": essays.get(kind),
        "highlights": r.get("highlights") or [],
        "notes": r.get("notes") or [],
        "history": [h.get("result", {}) | {"submitted_at": h.get("submitted_at")}
                    for h in (r.get("practice_result_history") or [])],
    }


if __name__ == "__main__":
    ck = "idictation_session=" + open(r"C:/Users/yyyyy/.workbuddy/.idict_ck").read().strip()
    for it in list_results(ck)["list"]:
        s = summarize(get_result(ck, it["id"]))
        print(s["kind"], s["paper_name"], s["word_count"], "词", s["total_score"], "分",
              {m: v["band"] for m, v in s["scores"].items()})
