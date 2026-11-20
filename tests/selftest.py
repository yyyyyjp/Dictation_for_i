#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线自检：不联网、不读账号，只用 tests/fixtures 里的合成数据验证归一化逻辑。

    python tests/selftest.py

用途：
  * 改 normalize.py 后回归，确认没有把某个字段改坏；
  * 换到别的 agent / 别的机器上时，先跑它确认 Python 环境与中文编码正常。

全部通过退出码 0，任一断言失败退出码 1。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import normalize as nz  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  -> " + str(detail)) if not cond else ""))


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_reading():
    raw = load("reading_raw.json")
    item = {"part_id": 9901, "topics": ["测试"], "done": True}
    ent = nz.reading_entities(raw, item)
    qs, ps, at = ent["questions"], ent["passage"], ent["attempt"]

    check("reading: 4 道题", len(qs) == 4, len(qs))
    check("reading: ID 可重建", qs[0]["question_id"] == "reading:9901:90001", qs[0]["question_id"])
    check("reading: 填空题干来自 collect", "first note is" in qs[0]["stem"], qs[0]["stem"])
    check("reading: 表格/多选共享选项被继承", len(qs[2]["options"]) == 3, len(qs[2]["options"]))
    check("reading: 多选题干来自组标题", qs[2]["stem"].startswith("Which TWO"), qs[2]["stem"])
    check("reading: 空答判为 blank 而非 wrong", qs[1]["state"] == "blank", qs[1]["state"])
    check("reading: 错因标签解析", qs[1]["error_tags"] == ["单词不认识"], qs[1]["error_tags"])
    check("reading: 正确率按题复算", abs(at["accuracy"] - 0.75) < 1e-6, at["accuracy"])
    check("reading: 段落 A/B 还原", [p["label"] for p in ps["paragraphs"]] == ["A", "B"],
          ps["paragraphs"])
    check("reading: 句子落回段落", ps["sentences"][0]["paragraph"] == "A",
          ps["sentences"][0]["paragraph"])
    check("reading: 高亮定位到段", at["marks"]["highlights"][0]["paragraph"] == "A",
          at["marks"]["highlights"][0])
    check("reading: HTML 标签被清掉", "<p>" not in json.dumps(ent, ensure_ascii=False))


def test_listening():
    raw = load("listening_raw.json")
    item = {"part_id": 99001, "test_id": 9901, "done": True, "accuracy": 100,
            "duration_sec": 600, "question_range": "1-4", "topics": ["测试"],
            "raw_answer": json.dumps([
                {"id": 91001, "answer": "9", "group_id": 21},
                {"id": 91002, "answer": "entry", "group_id": 21},
                {"id": 0, "answer": ["A", "B"], "group_id": 22},
            ])}
    ent = nz.listening_entities(raw, [item])
    qs, at = ent["questions"], ent["attempts"][0]

    check("listening: 4 道题", len(qs) == 4, len(qs))
    check("listening: 按 Part 拆 attempt", len(ent["attempts"]) == 1, len(ent["attempts"]))
    check("listening: 数字写法宽容（9=nine）", qs[0]["is_correct"] is True, qs[0]["yours"])
    check("listening: 表格题干拼出上下文", "Open at" in qs[0]["stem"], qs[0]["stem"])
    check("listening: 多选题组判定", qs[2]["state"] == "correct", qs[2]["state"])
    check("listening: 组内两题共用答案", qs[3]["yours"] == "A, B", qs[3]["yours"])
    check("listening: attempt 正确率", abs(at["accuracy"] - 1.0) < 1e-6, at["accuracy"])
    check("listening: result_id 取自 history", at["result_id"] == 8801, at["result_id"])
    check("listening: 音频直链保留", ent["passages"][0]["audio"]["part_url"].endswith(".mp3"))
    check("listening: 翻译来自 content", ent["passages"][0]["sentences"][0]["translation"] == "你好。")


def test_writing():
    raw = load("writing_raw.json")
    w = nz.writing_entity(raw)
    check("writing: 识别为大作文", w["task"] == "task_2", w["task"])
    check("writing: 词数", w["essay"]["word_count"] == 14, w["essay"]["word_count"])
    check("writing: 两个模型有分", len(w["scoring"]["models"]) == 2, w["scoring"]["models"].keys())
    check("writing: 模型分歧可量化", w["scoring"]["consensus"]["band_spread"] == 0.5,
          w["scoring"]["consensus"])
    check("writing: 四维齐全", len(list(w["scoring"]["models"].values())[0]["dimensions"]) == 4)
    check("writing: 范文保留", w["sample_essay"]["title"] == "7分范文", w["sample_essay"])


def test_classify():
    cases = [
        ("Which paragraph contains the following information?", "matching_paragraph"),
        ("Do the following statements agree with the information given? write TRUE / FALSE / NOT GIVEN", "tfng"),
        ("Choose the correct heading for each section from the list of headings", "matching_heading"),
        ("Choose TWO letters, A-E.", "mcq_multi"),
        ("Complete the notes below.", "completion_note"),
        ("Label the map below.", "labelling_map"),
        ("Answer the questions below. NO MORE THAN THREE WORDS", "short_answer"),
    ]
    for text, want in cases:
        got, _ = nz.classify(text)
        check("classify: %s -> %s" % (want, got), got == want, text[:50])


def main():
    print("== 合成数据自检 ==")
    for fn in (test_classify, test_reading, test_listening, test_writing):
        print("\n[%s]" % fn.__name__)
        fn()
    print("\n通过 %d 项，失败 %d 项" % (len(OK), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
