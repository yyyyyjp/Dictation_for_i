# 移植手册（PORTING）

> 目标：这套东西**不绑定 WorkBuddy**。换 agent、换电脑、甚至换一个雅思平台，都只需要改一层。
> 本文档写给两类人：把技能搬到别的 agent 的人，和把脚本接到别的题库平台的人。

---

## 1. 先理解分层：哪一层该改

```
┌───────────────────────────────────────────────┐
│ export.py        编排：选科目/书目 → 并发 → 落盘      │  ← 换平台时基本不用动
├───────────────────────────────────────────────┤
│ normalize.py     映射：原始 JSON → 统一 schema      │  ← 换平台时改这里
├───────────────────────────────────────────────┤
│ idict_client.py  通道：签名 / 重试 / 缓存 / cookie   │  ← 换平台时重写这里
└───────────────────────────────────────────────┘
        summary.py / validate.py 只依赖 schema，不依赖平台
```

判据很简单：

- **接口路径、签名、分页、登录方式变了** → 只改 `idict_client.py`。
- **返回 JSON 的字段名/嵌套变了，但语义还在** → 只改 `normalize.py`。
- **想加一门课（比如口语）** → 在 `normalize.py` 加一个 `speaking_entity()`，在 `export.py` 加一个分支，schema 加一个 `module` 枚举值。
- **只想换输出格式（CSV/Parquet/SQLite）** → 只改 `export.py` 的落盘函数，别动前两层。

## 2. 宿主能力矩阵

| 能力 | WorkBuddy | Antigravity | DeepSeek Harness | 通用 CLI agent |
|---|---|---|---|---|
| 读 `SKILL.md` | ✅ 原生 | ❌（读 `AGENTS.md`） | ❌（读 system prompt） | 视实现 |
| 读 `AGENTS.md` | 部分 | ✅ 通常 | ✅ 通常 | 多数支持 |
| 执行 shell | ✅ | ✅（集成终端） | ✅ | ✅ |
| 读写任意文件 | ✅ | ✅ | ✅ | ✅ |
| 后台长任务 | ✅ | ✅ | 视实现 | 视实现 |
| 无网络沙箱 | 否 | 否 | 可能 | 可能 |

**结论**：真正的硬要求只有两条 —— **能跑 `python3`**、**能读写工作目录**。其余都是「把哪份说明喂给模型」的差别。

### 各宿主接法

| 宿主 | 步骤 | 细节 |
|---|---|---|
| **WorkBuddy** | 把整个目录放到 `~/.workbuddy/skills/ielts-practice-export/`，重启会话 | `SKILL.md` 的 frontmatter 会被解析成技能描述；用 `bin/install.py` 一键装 |
| **Antigravity** | 项目根放 `AGENTS.md`；若版本支持 Rules/Knowledge，把 `AGENTS.md` 粘进去 | 见 `adapters/antigravity.md` |
| **DeepSeek Harness** | 把 `adapters/deepseek-harness.md` 的 system prompt 段贴进会话/配置，工作目录设为技能根 | 见该文件 |
| **其它** | 先让 agent 读 `AGENTS.md`，再让它执行三条命令 | 若宿主不能执行 shell，见 §5「无 shell 兜底」 |

## 3. 五步移植到新 agent

1. **确认 Python**：`python3 --version`。Windows 上 `python --version`。要求 **3.8+**：四个脚本都带了 `from __future__ import annotations`，所以 `str | None` 这类写法在 3.8 也能解析；如果你删掉这行 import，就需要 3.10+。
2. **跑离线自检**：`python3 tests/selftest.py`。这一步不联网，能验证解释器、中文编码、路径。
3. **喂登录态**：`--cookie` / `IDICT_COOKIE` / 文件三选一。首次建议显式传参，避免宿主环境变量污染。
4. **小样本试跑**：`--modules reading --limit 2 --keep-raw`，看 `meta.json.warnings` 是否为空。
5. **全量 + 校验**：去掉 `--limit`，跑 `validate.py`，再读 `summary.md`。

> 宿主差异最大的是**工作目录**。脚本里所有路径都支持绝对路径，建议显式传 `--out /abs/path`，别依赖 cwd。

## 4. 换一个数据源（不是 idictation）

### 4.1 最小改造：让新客户端返回「同形状的原始 JSON」

`normalize.py` 只认字段语义，不认域名。只要新平台的响应能拼成同样的结构，`normalize.py` 一行不用改。

阅读需要的字段（括号内为可缺省）：

```
paper_id, jianya_name, test_name, title
content{title, pre-A, A..Z, order_ary}          # 段落；缺了会标 sentences_only
new_content[{sentence, translation, grammar_analysis}]
question[{desc, type, group_id, title, collect, table, collect_option,
          list[{id, number, title, display_answer, answers, option,
                locating_words, key_locating_words, central_sentences, ai_analyze}]}]
practice_result{id, user_id, duration, zhengquelv, created_at, action,
                result_blanks[{blank_id, answer, correct_answer, is_correct}],
                highlights[], notes[]}
reports{blank_id: {types, description}}
```

听力额外需要：`parts[{paper_id, title, file_url, full_audio, content[], content_jingting[], question[]}]`，
以及目录页每个 Part 的 `practice_result.answer`（JSON 字符串，含 `id/answer/group_id`；多选题 `id=0`）。

写作需要：`id, dazuowen_paper_id, xiaozuowen_paper_id, {kind}_content, {kind}_word_count,
duration, total_score, {kind}_{qwen|deepseek|doubao}_score_details, corrections,
sample_essay, dazuowen_paper{content, content_category, name}`。

### 4.2 字段改名了怎么办

在 `normalize.py` 里加一个 `pick()` 兜底，不要写 `if 平台A / elif 平台B` 散落各处：

```python
def pick(d, *names, default=None):
    for n in names:
        if isinstance(d, dict) and d.get(n) not in (None, ""):
            return d[n]
    return default

# 用法：题干可能是 title，也可能是 text
stem = pick(q, "title", "text")
```

### 4.3 判定口径不同怎么办

- 官方给了逐题判定（如 `result_blanks.is_correct`）→ **优先信官方**，别自己复算。
- 只给标准答案 → 用 `judge()` 本地比；不同平台的宽容度不同，把规则集中在 `judge()`，并在 `meta.json.conventions` 里写清楚。
- 永远保留 `accuracy_raw`（平台原值）与 `accuracy`（本工具复算值）两个字段，方便对账。

### 4.4 schema 演进规则

- 加字段：直接加，`schema_version` 升 minor（1.0 → 1.1）。
- 改字段名/删字段：升 major（1.x → 2.0），并在 `CHANGELOG.md` 给迁移说明。
- 实验性字段一律塞 `extra`，不要污染主字段。
- 任何改动后跑 `tests/selftest.py`；新增分支就加一条 fixture 断言。

## 5. 宿主差异与兜底

### 无 shell 的宿主

让用户在系统终端手动跑：

```bash
python3 /path/to/ielts-practice-export/scripts/export.py --out /path/to/ielts-data
```

然后把 `summary.md` 与 `questions.jsonl` 的前 N 行贴进对话。**不要让模型"模拟"接口**，一定跑真脚本。

### Windows 编码

- 脚本全部 `encoding="utf-8"`，CSV 用 `utf-8-sig` 以兼容 Excel。
- 如果宿主是 cmd.exe 且输出中文乱码：`chcp 65001`。
- 路径含空格/中文时用双引号包住。

### 无网络 / 需要代理

- `URLError` 会重试 2 次后抛 `ConnectionError`（退出码 3）。
- 需要代理时在宿主侧设 `HTTPS_PROXY`，`urllib` 会自动读取。

### 超时与限速

- 默认 `--workers 4`，单请求 30–90 秒。全库 216 篇阅读约 1–3 分钟。
- 站点返回空对象（`{}`）不一定是限速，可能是个别篇目数据缺失；看 `warnings`。

## 6. 隐私与合规（重要）

- `idictation_session` 是登录凭证，等同密码。**不要**写进 `meta.json`、日志、git。
- 本工具只调用查询接口；不要添加任何 `submit/score/delete` 调用。
- `passages.jsonl` 含剑桥雅思原文，**有版权**。仅限本人学习复盘；不要上传公开仓库、不要二次分发。
- 若要把数据集交给第三方模型，先确认对方的数据使用条款；必要时用 `--modules writing` 只导自己写的内容。

## 7. 移植检查清单

- [ ] `python3 tests/selftest.py` 全绿
- [ ] `--dry-run` 能看到目录（阅读 216 / 听力 288 / 写作 144，或你的账号实际规模）
- [ ] 小样本 `--limit 2` 的 `warnings` 为空
- [ ] `validate.py` 输出「通过」
- [ ] `meta.json` 里 `schema_version`、`counts`、`conventions` 符合预期
- [ ] 用 `summary.md` 的「练习单元」数与用户记忆交叉核对
- [ ] 确认产出目录里没有 cookie、没有 `raw/`（如果不想留）
- [ ] 跨设备合并时：`attempt_id` 不冲突（同一账号同一 result_id 会命中同一条）

## 8. 已知边界

| 限制 | 说明 | 影响 |
|---|---|---|
| 无单题用时 | 平台只给整篇/整 Part 用时 | 不能做「每题耗时」分析 |
| 部分篇目无段落 | 站点只给逐句 | `paragraph_source="sentences_only"` |
| 听力判定为本地复算 | 大小写/冠词/数字宽容，拼写错仍算错 | 与站点可能 ±1 题 |
| 多选题整组判定 | 平台一条记录代表整组 | 组内两题同对同错 |
| 写作只有当前版本 | 历史多稿不在结果接口里 | 只能看最后一次 |
| 接口为私有契约 | 无版本号、无文档 | 改版需修 `idict_client.py` |
