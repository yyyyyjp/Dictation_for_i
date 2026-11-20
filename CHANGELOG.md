# 变更记录

## 1.0.0 — 2026-11-21

首个可移植版本。

### 能力

- 导出 idictation.cn 的阅读 / 听力 / 写作作答数据，归一化为 schema v1.0。
- 阅读：段落原文、逐句中英对照、语法拆解、官方定位词/同义替换/中心句、AI 解析、自标错因、高亮与笔记。
- 听力：转写与毫秒时间轴、逐句翻译、两种来源的语法分析对齐、按 Part 拆分的提交记录、多选题组判定、目标分与错词本。
- 写作：题目、正文、qwen/deepseek/doubao 三模型评分与四维明细、模型分歧度、批注、范文、历史提交。
- 支持 `--include-undone` 建全库答案库（阅读 216 篇 / 听力 288 Part / 写作 144 题）。
- 支持 A 类 / G 类阅读、剑雅 / 机经听力、真题 / 机经 / G 类写作（`--reading-source` 等参数）。
- 生成 `summary.md` 与 `analysis_prompt.md`。

### 工程

- 零第三方依赖，Python 3.8+。
- 请求缓存（URL + 参数哈希）、并发、重试、签名。
- `validate.py` 结构校验；`tests/selftest.py` 离线回归（合成数据）。
- 跨 agent 文档：`SKILL.md` / `AGENTS.md` / `PORTING.md` / `adapters/*`。

### 已知问题

- 少数篇目站点只提供逐句、不提供段落，标记 `paragraph_source="sentences_only"`。
- 听力判分为本地复算，与站点可能有 ±1 题差异；对账用 `accuracy_raw`。
- 写作历史多稿仅保留当前版本（平台接口限制）。

### 兼容性

- schema v1.0；后续加字段升 minor，改字段升 major。
