#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""idictation.cn 原始数据客户端（零依赖，Python 3.8+）。

职责边界：只负责「怎么把原始 JSON 拿回来」——签名、重试、缓存、Cookie 解析。
字段怎么解读、怎么归一化，全部放在 normalize.py，方便单独替换。

快速用法::

    from idict_client import IdictClient, resolve_cookie

    cli = IdictClient(resolve_cookie())
    parts = cli.reading_catalog()                  # 216 条
    raw = cli.reading_part(parts[0]["part_id"])    # 单篇原始响应

对接其它平台时：只要实现同名方法并返回同等结构的 dict，normalize.py 可原样复用。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import re
import string
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://www.idictation.cn"
SECRET = "idictation_2024"          # 前端硬编码的签名密钥，非用户凭证
UA = "Mozilla/5.0 (compatible; ielts-practice-export/1.0)"

# 阅读：A 类真题 / G 类真题（路径只差 yuedu- 与 yuedu-g-）
READING_LIST = "/api/study/yuedu-zhenti/v1/jianya/list"
READING_SHOW = "/api/study/yuedu-zhenti/v1/jianya/part/show/"
# 听力：剑雅真题 / 机经
LISTENING_LIST = "/api/study/zhenti/v1/test/list"
LISTENING_SHOW = "/api/study/zhenti/v1/test/show/"
LISTENING_JJ_LIST = "/api/study/zhenti/v1/jj/list"
# 写作：真题 / 机经 / G 类
WRITING_MODULES = {
    "zhenti": "xiezuo-zhenti",
    "jijing": "xiezuo-jijing",
    "g": "xiezuo-g-zhenti",
}

COOKIE_CANDIDATES = (
    "~/.workbuddy/.idict_ck",
    "~/.idict_ck",
    "~/.config/idictation/cookie",
    "~/.config/idictation/.idict_ck",
    "~/.ielts/idictation.cookie",
    "./.idict_ck",
)


class AuthError(PermissionError):
    """登录态缺失或过期。"""


# ------------------------------------------------------------------ Cookie
def _normalize_cookie(raw: str) -> str:
    """接受裸 session 值、`idictation_session=...`、或含该键的 JSON。"""
    raw = (raw or "").strip().strip('"').strip("'")
    if not raw:
        raise AuthError("Cookie 为空")
    if raw.startswith("{"):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            obj = {}
        for key in ("idictation_session", "cookie", "Cookie", "value"):
            if isinstance(obj.get(key), str) and obj[key].strip():
                raw = obj[key].strip()
                break
    raw = re.sub(r"^idictation_session\s*=\s*", "", raw)
    if ";" in raw:                                   # 粘了一整串 document.cookie
        m = re.search(r"idictation_session=([^;]+)", raw)
        if m:
            raw = m.group(1)
        else:
            raw = raw.split(";")[0].split("=")[-1]
    return "idictation_session=" + raw


def resolve_cookie(explicit: str | None = None,
                   cookie_file: str | None = None,
                   extra_candidates: list[str] | None = None) -> str:
    """按优先级找登录态：显式传入 > 环境变量 > 候选文件。

    找不到时抛 AuthError，并给出获取步骤（不静默失败，避免导出空数据集）。
    """
    if explicit:
        return _normalize_cookie(explicit)

    env = os.environ.get("IDICT_COOKIE")
    if env:
        return _normalize_cookie(env)
    env_file = os.environ.get("IDICT_COOKIE_FILE")
    if env_file:
        return _normalize_cookie(Path(env_file).expanduser().read_text(encoding="utf-8"))

    paths = []
    if cookie_file:
        paths.append(cookie_file)
    paths.extend(extra_candidates or [])
    paths.extend(COOKIE_CANDIDATES)
    for p in paths:
        fp = Path(p).expanduser()
        if fp.is_file():
            txt = fp.read_text(encoding="utf-8", errors="ignore").strip()
            if txt:
                return _normalize_cookie(txt)

    raise AuthError(
        "未找到 idictation 登录态。请任选一种方式提供：\n"
        "  1) --cookie 'idictation_session=xxxx'\n"
        "  2) 环境变量 IDICT_COOKIE=xxxx\n"
        "  3) --cookie-file <文件>，文件内写裸值或 idictation_session=xxxx\n"
        "  4) 放到以下任一位置：" + "、".join(COOKIE_CANDIDATES[:4]) + "\n"
        "获取方法：浏览器登录 https://www.idictation.cn → F12 → "
        "Application/存储 → Cookies → 复制 idictation_session 的值。\n"
        "注意：该值等同登录凭证，不要提交到 git 或公开分享。"
    )


# ------------------------------------------------------------------ 签名
def sign_params(data: dict) -> str:
    """HMAC-SHA256(secret, "k=v&k=v"，key 升序)；复合值先紧凑 json。"""
    parts = []
    for k in sorted(data):
        if k == "sign":
            continue
        v = data[k]
        if isinstance(v, (dict, list)):
            v = json.dumps(v, separators=(",", ":"), ensure_ascii=False)
        parts.append("%s=%s" % (k, v))
    msg = "&".join(parts).encode("utf-8")
    return hmac.new(SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()


# ------------------------------------------------------------------ Client
class IdictClient:
    def __init__(self, cookie: str, base: str = BASE, timeout: int = 30,
                 retries: int = 2, cache_dir: str | None = None):
        self.cookie = _normalize_cookie(cookie)
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.calls = 0
        self.cache_hits = 0

    # -- 底层 ---------------------------------------------------------
    def _cache_path(self, path: str, payload: dict) -> Path | None:
        """缓存键必须含 payload：writing/results/show 同一路径靠 body 区分 id。"""
        if not self.cache_dir:
            return None
        sig = ""
        if payload:
            sig = hashlib.md5(
                json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:10]
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", path).strip("_")[-100:]
        return self.cache_dir / ("%s%s.json" % (safe, ("." + sig) if sig else ""))

    def post(self, path: str, payload: dict | None = None,
             timeout: int | None = None, cache: bool = True) -> dict:
        """POST 一个接口，返回 values 内层 dict。"""
        payload = payload or {}
        cpath = self._cache_path(path, payload) if cache else None
        if cpath and cpath.is_file():
            try:
                self.cache_hits += 1
                return json.loads(cpath.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass

        body = {k: v for k, v in payload.items() if v is not None and v != ""}
        body["api_key"] = urllib.parse.quote(path, safe="")
        body["timestamp"] = int(time.time())
        body["nonce"] = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        body["sign"] = sign_params(body)

        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Cookie": self.cookie,
                     "Referer": self.base + "/", "User-Agent": UA},
            method="POST",
        )

        last_exc = None
        for attempt in range(self.retries + 1):
            try:
                self.calls += 1
                with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                    raw = json.loads(r.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise AuthError("登录态失效（HTTP %s），请重新获取 idictation_session" % e.code)
                last_exc = e
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
                last_exc = e
            if attempt < self.retries:
                time.sleep(1.2 * (attempt + 1))
        else:
            raise ConnectionError("请求失败 %s: %s" % (path, last_exc))

        if isinstance(raw, dict) and raw.get("status") == 401:
            raise AuthError("登录态失效（status=401），请重新获取 idictation_session")

        values = raw.get("values", raw) if isinstance(raw, dict) else raw
        if not isinstance(values, dict):
            values = {"values": values}

        if cpath:
            cpath.parent.mkdir(parents=True, exist_ok=True)
            cpath.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
        return values

    # -- 目录 ---------------------------------------------------------
    def reading_catalog(self, source: str = "jianya") -> dict:
        path = READING_LIST if source != "g" else READING_LIST.replace("yuedu-", "yuedu-g-")
        return self.post(path, {"page": 1, "limit": 500}, timeout=90)

    def listening_catalog(self, source: str = "jianya") -> dict:
        path = LISTENING_LIST if source != "jijing" else LISTENING_JJ_LIST
        return self.post(path, {"page": 1, "limit": 500}, timeout=90)

    def writing_catalog(self, kind: str = "dazuowen", module: str = "zhenti") -> dict:
        return self.post(self._writing_base(module) + "/%s/list" % kind,
                         {"page": 1, "limit": 500}, timeout=90)

    def writing_results(self, module: str = "zhenti", page: int = 1,
                        limit: int = 100) -> dict:
        return self.post(self._writing_base(module) + "/results/list",
                         {"page": page, "limit": limit}, timeout=90)

    # -- 详情 ---------------------------------------------------------
    def reading_part(self, part_id: int, source: str = "jianya") -> dict:
        path = READING_SHOW if source != "g" else READING_SHOW.replace("yuedu-", "yuedu-g-")
        return self.post(path + str(part_id), {}, timeout=90)

    def listening_test(self, test_id: int) -> dict:
        return self.post(LISTENING_SHOW + str(test_id), {}, timeout=90)

    def listening_part(self, paper_id: int) -> dict:
        """机经听力没有 test 维度，详情按 Part 取。"""
        return self.post("/api/study/zhenti/v1/jj/part/show/" + str(paper_id), {}, timeout=90)

    def writing_result(self, result_id: int, module: str = "zhenti") -> dict:
        v = self.post(self._writing_base(module) + "/results/show",
                      {"id": result_id}, timeout=90)
        return v.get("result") or {}

    @staticmethod
    def _writing_base(module: str) -> str:
        return "/api/study/%s/v1" % WRITING_MODULES.get(module, module)


# ------------------------------------------------------------------ 目录扁平化
def flatten_catalog(raw: dict, module: str, source: str = "jianya") -> list[dict]:
    """把目录压平成一行一个练习单元。

    两种结构：
      * 剑雅：books → children(Test) → children(Part)
      * 机经听力：books → parts（没有 Test 层）
    """
    out = []
    raw = raw or {}

    if module == "listening" and source == "jijing":
        for book in raw.get("books") or []:
            for part in book.get("parts") or []:
                pr = part.get("practice_result") or {}
                out.append({
                    "module": module,
                    "source": source,
                    "book": book.get("name"),
                    "test": part.get("test_name"),
                    "title": part.get("title"),
                    "part_id": part.get("paper_id"),
                    "test_id": book.get("test_id"),
                    "done": bool(pr),
                    "accuracy": pr.get("zhengquelv"),
                    "duration_sec": mr_duration(pr.get("duration")),
                    "raw_answer": pr.get("answer"),
                    "question_range": part.get("question_name"),
                    "question_types": part.get("question_type"),
                    "topics": part.get("topic"),
                    "total_num": part.get("total_num"),
                })
        return out

    for book in raw.get("books") or []:
        for test in book.get("children") or []:
            for part in test.get("children") or []:
                pr = part.get("practice_result") or {}
                item = {
                    "module": module,
                    "source": source,
                    "book": book.get("name"),
                    "test": test.get("name"),
                    "title": part.get("title") or part.get("name"),
                    "part_id": part.get("id") or part.get("paper_id"),
                    "test_id": test.get("test_id"),
                    "done": bool(pr),
                    "accuracy": pr.get("zhengquelv"),
                    "duration_sec": mr_duration(pr.get("duration")),
                    "raw_answer": pr.get("answer"),
                    "question_range": part.get("question"),
                    "question_types": part.get("question_type"),
                    "topics": part.get("topic"),
                    "total_num": part.get("total_num"),
                }
                if module == "writing":
                    item["kind"] = part.get("kind") or None
                    item["paper_id"] = part.get("paper_id") or part.get("id")
                    item["part_id"] = item["paper_id"]
                out.append(item)
    return out


def mr_duration(v):
    """站点部分字段用毫秒，部分用秒；>10000 视为毫秒。"""
    if v in (None, "", 0):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n // 1000 if n > 10000 else n


if __name__ == "__main__":  # 连通性自检：python idict_client.py
    cli = IdictClient(resolve_cookie())
    for label, fn in (("阅读", cli.reading_catalog),
                      ("听力", cli.listening_catalog),
                      ("写作-大", lambda: cli.writing_catalog("dazuowen"))):
        try:
            rows = flatten_catalog(fn(), "reading")
            print("%s 目录: %d 个练习单元" % (label, len(rows)))
        except Exception as e:  # noqa: BLE001
            print("%s 失败: %s" % (label, e))
    print("HTTP 调用 %d 次，缓存命中 %d 次" % (cli.calls, cli.cache_hits))
