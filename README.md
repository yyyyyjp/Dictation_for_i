# ielts-practice-export

把 idictation.cn 上的雅思阅读 / 听力 / 写作作答记录，导出成一套**结构稳定、可跨设备合并、可直接喂给模型**的数据集。

零第三方依赖，Python 3.8+，只读，不碰账号。

## 它产出什么

```
ielts-data/
├── meta.json          导出元信息（范围、计数、哈希、告警）
├── catalog.jsonl      一行一个练习单元（含没做过的）
├── attempts.jsonl     一行一次提交（正确率、用时、分题型小计、高亮笔记）
├── questions.jsonl    一行一道题（答案、判定、定位词、中心句、AI 解析）
├── groups.jsonl       一行一个题组（指令、共享选项、笔记/表格原文）
├── passages.jsonl     一行一篇原文/转写（段落、句子、翻译、语法、音频）
├── writing.jsonl      一行一篇作文（正文、三模型评分、批注、范文）
├── summary.md         人读总览
└── analysis_prompt.md 可直接粘贴的分析指令
```

## 快速开始

```bash
python3 tests/selftest.py                       # 1. 离线自检
export IDICT_COOKIE='xxxx'                      # 2. 登录态（见下）
python3 scripts/export.py --out ./ielts-data    # 3. 导出
python3 scripts/validate.py --in ./ielts-data   # 4. 校验
```

完整步骤、参数与排错见 `SKILL.md`。

## 登录态

浏览器登录 <https://www.idictation.cn> → F12 → Application（存储）→ Cookies → 复制 `idictation_session`。

三种给法：`--cookie`、`IDICT_COOKIE` 环境变量、写到 `~/.workbuddy/.idict_ck`。
**这是登录凭证，不要提交到 git。**

## 安装到 agent

| 宿主 | 做法 |
|---|---|
| WorkBuddy | `python3 bin/install.py` → 重开会话 |
| Antigravity | 项目根放 `AGENTS.md`，见 `adapters/antigravity.md` |
| DeepSeek Harness | 粘贴 `adapters/deepseek-harness.md` 的 system prompt |
| 其它 | 让 agent 读 `AGENTS.md`，或参考 `PORTING.md` |

## 设计

```
export.py      编排：选科目/书目 → 并发 → 落盘
normalize.py   映射：原始 JSON → 统一 schema（换平台只改这层）
idict_client.py 通道：签名/重试/缓存/cookie（换平台重写这层）
summary.py     汇报：summary.md + analysis_prompt.md
validate.py    校验：字段、枚举、ID 唯一性
```

字段定义见 `schema/field-dictionary.md`；机器可读 schema 见 `schema/dataset.schema.json`。

## 数据边界

平台**不提供**单题用时、作答轨迹；少数篇目只有逐句没有段落；写作只保留当前版本。
这些都在字段字典的「常见误读」里写清楚了，不要把它们解读成「没做」。

## 合规

- 只调用查询接口，不提交、不改分。
- 题库原文有版权，仅限本人复盘，不要公开分发。
- 接口是站点前端私有契约，平台改版可能失效。

## 版本

- 技能版本：1.0.0
- schema 版本：1.0（加字段升 minor，改字段升 major）
- 变更记录：`CHANGELOG.md`
