# Antigravity 接法

> Antigravity 的规则/知识入口会随版本变化（Rules、Knowledge、AGENTS.md 的支持情况不一致）。
> 本文给的是**能力要求 + 三种可用接法**，不写死某个版本的路径。以你本机 Help/Docs 为准。

## 需要宿主具备的能力

1. 执行终端命令（`python3`）。
2. 读写项目目录。
3. 能读到一个「入口说明」文件（`AGENTS.md` 或 Rules/Knowledge 里的文本）。

三条都满足就能用；缺第 1 条见文末兜底。

## 接法 A：项目根放 AGENTS.md（推荐）

把本目录整体放进你的雅思项目（例如 `~/ielts/`），确保 `AGENTS.md` 在项目根：

```
~/ielts/
├── AGENTS.md                 ← 从技能目录复制过来
├── ielts-practice-export/    ← 技能本体
└── ielts-data/               ← 导出产物
```

然后对 agent 说：

> 读 AGENTS.md，按里面的三条命令导出我的雅思数据，出问题先跑 selftest。

## 接法 B：Rules / Knowledge

如果当前版本有 Rules 或 Knowledge 面板：

1. 新建一条规则，标题 `ielts-practice-export`。
2. 把 `AGENTS.md` 全文粘进去。
3. 把触发条件写成一行：「用户提到导出/备份/分析雅思练习数据时，按此规则执行」。
4. 在规则里写死技能绝对路径，避免它猜 cwd。

## 接法 C：会话内直接注入

临时用一次：把 `AGENTS.md` 全文粘进会话首条消息，并补一句：

> 技能根目录是 `<绝对路径>`；所有命令都在该目录下执行。

## 执行要点

- 用绝对路径：`python3 /abs/path/scripts/export.py --out /abs/path/ielts-data`
- 首次先 `--limit 2`，确认 `meta.json.warnings` 为空再全量。
- 需要看原文时，让 agent 按 `passage_id` 读 `passages.jsonl`，不要整份加载。
- Antigravity 的 Artifact 适合展示 `summary.md`；JSONL 不要直接塞进上下文。

## 兜底：宿主不能执行 shell

在系统终端手动跑：

```bash
cd /abs/path/ielts-practice-export
python3 tests/selftest.py
python3 scripts/export.py --out /abs/path/ielts-data
```

然后把 `summary.md` 贴进对话，让 agent 基于它做分析；需要下钻时再贴 `questions.jsonl` 的片段。

**不要让模型凭记忆"模拟"导出结果。**
