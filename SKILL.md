---
name: ielts-practice-export
description: 从 idictation.cn 导出本人账号的雅思阅读、听力、写作作答数据，归一化为稳定 schema 的 JSONL 数据集，并生成 summary.md 与分析指令。当用户提出「导出/备份我的雅思练习数据」「把阅读听力作文的作答整理成结构化表格」「分析我的错题和薄弱项」「建立剑雅全库答案库」「换电脑/换 agent 后继续复盘」等需求时使用。支持 WorkBuddy、Antigravity、DeepSeek Harness 以及任何能执行 Python 的 agent；只读，仅限本人账号。
agent_created: true
version: 1.0.0
schema_version: "1.0"
---

# 雅思练习数据导出（idictation.cn）

## 这个技能解决什么

把散在网页里的作答记录，变成**一份可长期保存、可跨设备合并、可喂给任何模型分析**的数据集：

- 逐题：我的答案 / 正确答案 / 对错 / 官方定位词 / 同义替换 / 中心句 / AI 解析 / 自标错因
- 原文：阅读段落 A–Z + 逐句中英对照 + 语法拆解；听力转写 + 毫秒时间轴 + 翻译
- 写作：题目 / 我的正文 / qwen·deepseek·doubao 三模型评分与四维明细 / 批注 / 范文
- 元数据：用时、提交时间、重复刷题历史、高亮与笔记

它不替你做分析，只保证**分析之前的脏活已经干完**。

## 何时使用

- 「导出我的雅思练习记录」「备份一下，怕平台哪天关了」
- 「把我的错题整理成 Excel / 给 AI 看的数据」
- 「我在别的电脑/别的 agent 上还想接着复盘」
- 「我要统计剑雅全库某个题型的答案分布」（用 `--include-undone`）
- 「对比我三次模考的题型正确率变化」

不适用：抓别人账号、批量刷题、绕过付费、分发题库原文。

## 30 秒快速开始

```bash
# 0) 只需要 Python 3.8+，不装任何第三方包
python3 --version

# 1) 先跑离线自检，确认环境没问题（不联网）
python3 tests/selftest.py

# 2) 取登录态（见下一节），然后导出
python3 scripts/export.py --out ./ielts-data

# 3) 校验 + 看总览
python3 scripts/validate.py --in ./ielts-data
cat ./ielts-data/summary.md
```

产物在 `./ielts-data/`：6 个 JSONL + `summary.md` + `analysis_prompt.md` + `meta.json`。

## 第一步：取登录态

三种方式任选，优先级从高到低：

| 方式 | 写法 |
|---|---|
| 命令行 | `--cookie 'idictation_session=xxxx'` |
| 环境变量 | `export IDICT_COOKIE=xxxx`（Windows: `set IDICT_COOKIE=xxxx`） |
| 文件 | 写到 `~/.workbuddy/.idict_ck` 或 `~/.idict_ck`，内容为裸值或 `idictation_session=xxxx` |

获取方法：浏览器登录 <https://www.idictation.cn> → F12 → Application（存储）→ Cookies → 复制 `idictation_session` 的值。

> 这个值等同登录凭证。不要提交到 git、不要贴进公开对话。技能不会把它写进任何产出文件。

## 第二步：导出

```bash
# 默认：三科、只导做过的
python3 scripts/export.py --out ./ielts-data

# 只要阅读，且限定套书
python3 scripts/export.py --out ./ielts-data --modules reading --books 剑雅18,剑雅19

# 连没做过的篇目一起抓（建答案库 / 做全库题型统计）
python3 scripts/export.py --out ./ielts-data --include-undone

# 保留原始响应 + 额外生成 Excel 友好的 CSV
python3 scripts/export.py --out ./ielts-data --keep-raw --csv
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--modules` | `reading,listening,writing` 的任意组合，默认全选 |
| `--books` | 只导这些套书，`剑雅18` 或 `18` 都行，逗号分隔 |
| `--include-undone` | 未做篇目也抓（题目 + 官方答案，无作答） |
| `--reading-source` | `jianya`（默认）/ `g` / `both` |
| `--listening-source` | `jianya`（默认）/ `jijing` / `both` |
| `--writing-module` | `zhenti`（默认）/ `jijing` / `g` |
| `--limit N` | 每科最多处理 N 个单元，调试用 |
| `--workers N` | 并发请求数，默认 4；别超过 8，站点会限速 |
| `--keep-raw` | 每个接口原始 JSON 存到 `raw/` |
| `--csv` | 额外输出 `questions.csv` |
| `--no-cache` | 忽略 `out/.cache/`，强制重新抓 |
| `--dry-run` | 只拉目录、打印数量，不抓详情 |

重跑很快：详情按 URL + 参数哈希缓存在 `out/.cache/`，同一份数据第二次几乎零请求。换账号或平台改版时加 `--no-cache`。

## 第三步：校验

```bash
python3 scripts/validate.py --in ./ielts-data
```

检查 JSON 可解析、必填字段齐全、`state` 枚举合法、`is_correct` 与 `state` 自洽、ID 不重复。**分析前先跑它**，比事后怀疑数据可靠得多。

## 第四步：分析

1. 先读 `summary.md`（分科 / 分题型 / 分位置 / 错题清单 / 用时）。
2. 再按需 grep `questions.jsonl`，不要整份塞进上下文。
3. 需要原文时按 `passage_id` 取 `passages.jsonl`。
4. 直接把 `analysis_prompt.md` 的内容作为分析指令。

分析时的三条硬规则（写进 `analysis_prompt.md` 了）：

- `state` 有四种：`correct / wrong / blank / unattempted`。**blank 是策略问题，wrong 是能力问题，别合并**。
- `is_correct = null` 表示没作答记录，不是「错」。
- 样本量 < 5 的题型只描述、不推论。

## 输出结构

```
ielts-data/
├── meta.json          导出元信息：schema 版本、范围、计数、文件哈希、告警
├── catalog.jsonl      一行一个练习单元（含未做），用来回答「我做过什么/还剩什么」
├── attempts.jsonl     一行一次提交：正确率、用时、分题型小计、高亮笔记
├── questions.jsonl    一行一道题 ← 分析主力
├── groups.jsonl       一行一个题组：指令、共享选项、笔记/表格原文
├── passages.jsonl     一行一篇原文/转写：段落、句子、翻译、语法、音频
├── writing.jsonl      一行一篇作文：正文、三模型评分、批注、范文
├── summary.md         人读总览
├── analysis_prompt.md 可直接粘贴的分析指令
├── questions.csv      仅 --csv
├── raw/               仅 --keep-raw，接口原始响应
└── .cache/            请求缓存，可安全删除
```

字段逐项说明见 `schema/field-dictionary.md`；机器可校验的 schema 见 `schema/dataset.schema.json`。

## 能到什么颗粒度

| 维度 | 阅读 | 听力 | 写作 |
|---|---|---|---|
| 我的答案 / 正确答案 | ✅ | ✅（本地复算判定） | — |
| 逐题对错 | ✅ 站点判定 | ✅ 宽松判分 | — |
| 题干 / 选项 | ✅ 三种存法都兜住 | ✅ 含组内共享选项 | 题目原文 |
| 官方解析 | ✅ 定位词+同义替换+中心句+AI | ✅ 同左 | 四维评分理由 |
| 原文 | ✅ 段落 A–Z + 逐句 | ✅ 转写 + 毫秒轴 | — |
| 翻译 / 语法 | ✅ 逐句 | ✅ 逐句 | — |
| 高亮 / 笔记 | ✅ 还原到段+字符位 | ❌ 平台未提供 | ✅ 原样 |
| 用时 | ✅ 整篇 | ✅ 每个 Part | ✅ 整篇 |

平台**不提供**：单题用时、作答轨迹、切屏记录、耳机音量。别把「没有」解读成「没做」。

## 关键约束

- **只读**。所有请求都是查询接口，不会提交、不会改分、不会触发重做。
- **cookie 即凭证**。技能不打印、不入库、不写进产出；排错时也不要贴给第三方。
- **接口是站点前端私有契约**。平台改版可能失效；先 `--dry-run` 确认目录能拉到，再全量。
- **题库原文有版权**。导出的 `passages.jsonl` 仅供本人学习复盘，不要公开分发。
- **判定口径**：阅读用站点 `result_blanks`；听力本地复算（大小写/冠词/数字写法宽容，拼写错仍算错），与站点可能有 ±1 题差异。要绝对对齐就用 `accuracy_raw`。

## 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| 退出码 2 / `登录态失效` | cookie 过期或粘错 | 重新复制 `idictation_session`；确认没有多带 `;` 后的内容 |
| 退出码 3 / `请求失败` | 网络或代理 | 检查能否打开 idictation.cn；重试 `--workers 1` |
| 退出码 4 / 0 条 attempt | 账号确实没做过，或书目过滤太窄 | `--dry-run` 看 `done` 数；去掉 `--books` |
| `warnings` 里有空响应 | 个别篇目站点数据缺失 | 换一篇验证；这些篇目会在 `meta.json.warnings` 列出 |
| 第二次跑没变化 | 走了缓存 | 加 `--no-cache` |
| 写作少了几篇 | `--writing-kinds` 默认只含大/小作文 | 确认 `kind`；`--writing-module jijing` 导机经 |
| 阅读某篇段落为空 | 站点只给了逐句、没给段落 | 看 `paragraph_source: "sentences_only"`，属数据缺口 |

## 跨 agent / 跨设备

同一套脚本可以在任何能执行 Python 的 agent 里跑。入口文件按宿主习惯选：

| 宿主 | 读哪个文件 | 安装位置 |
|---|---|---|
| WorkBuddy | `SKILL.md` | `~/.workbuddy/skills/ielts-practice-export/` |
| Antigravity | `AGENTS.md` + `adapters/antigravity.md` | 项目根或 Rules/Knowledge |
| DeepSeek Harness | `AGENTS.md` + `adapters/deepseek-harness.md` | system prompt / 工作区 |
| 其它 | `PORTING.md` | 任意目录 |

一键安装到 WorkBuddy：

```bash
python3 bin/install.py                 # 自动探测 ~/.workbuddy/skills
python3 bin/install.py --target /path/to/skills
```

详细适配说明（能力假设、替换点、字段映射）见 `PORTING.md`。

## 目录结构

```
ielts-practice-export/
├── SKILL.md                 本文件（WorkBuddy / Claude Skills 规范）
├── AGENTS.md                通用 agent 入口（Antigravity / DeepSeek / 其它）
├── README.md                人读说明
├── PORTING.md               跨 agent / 跨平台移植手册
├── CHANGELOG.md
├── manifest.json            版本、依赖、文件哈希（bin/package.py 生成）
├── adapters/                各宿主的具体接法
├── assets/analysis-prompt.md
├── bin/
│   ├── install.py           一键安装到 skills 目录
│   └── package.py           重建 manifest + 打 zip
├── schema/
│   ├── dataset.schema.json
│   └── field-dictionary.md
├── scripts/
│   ├── idict_client.py      接口客户端（签名/重试/缓存/cookie）
│   ├── normalize.py         原始 JSON → 统一 schema
│   ├── export.py            CLI 主程序
│   ├── summary.py           生成 summary.md / analysis_prompt.md
│   └── validate.py          结构校验
├── legacy/                  最早的三份一次性脚本（只作字段对照，勿直接跑）
└── tests/
    ├── selftest.py          离线回归（合成数据）
    └── fixtures/
```

改完脚本或文档后跑 `python3 bin/package.py`，会重建 `manifest.json` 并在 `dist/` 生成可分发 zip。
