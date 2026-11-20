# 通用 agent 接法（Claude Code / Cursor / Codex CLI / 自建 agent）

## 最小契约

任何 agent，只要满足下面四条，就能用这个技能，不需要额外适配：

1. 能执行 `python3`（3.8+）；
2. 能读写一个工作目录；
3. 能读到 `AGENTS.md`（或把它的内容注入 system prompt）；
4. 有网络出口（访问 `www.idictation.cn`）。

## 三步接入

```bash
# 1. 放到任意目录
git clone <你的仓库> ielts-practice-export   # 或直接拷贝文件夹

# 2. 自检（离线）
python3 ielts-practice-export/tests/selftest.py

# 3. 把 AGENTS.md 作为项目说明
cp ielts-practice-export/AGENTS.md ./AGENTS.md
```

然后对 agent 说：

> 读 AGENTS.md，导出我的雅思数据到 ./ielts-data，跑完校验并把 summary 的要点告诉我。

## 如果你要写自己的适配层

只需要包三件事：

```python
# 伪代码
cookie = ask_user_or_env("IDICT_COOKIE")
run("python3 scripts/export.py", out=OUT, cookie=cookie)

if run("python3 scripts/validate.py", src=OUT).code != 0:
    report_and_stop()

summary = read(OUT / "summary.md")
questions = iter_jsonl(OUT / "questions.jsonl")   # 按需过滤，别全量加载
```

要点：

- **别重写抓取逻辑**。接口有签名（HMAC-SHA256 + nonce + timestamp），自己拼容易错，直接用 `idict_client.py`。
- **别重写字段映射**。`normalize.py` 里每个兜底都是踩过坑的（三种题干存法、多选题 id=0、表格第 0 列占位符、段落缺失）。
- **输出目录可配置**。别写死 `./ielts-data`，宿主可能只允许写特定目录。

## 无文件系统 / 纯对话宿主

只能在终端手动跑，然后把结果贴进来。此时至少贴：

1. `summary.md` 全文；
2. `meta.json` 的 `counts` 与 `warnings`；
3. 需要分析的具体题目行（用 `grep` 过滤）。

## 多设备合并

同一账号在不同设备导出，`attempt_id` 由 `module:part_id:result_id` 生成，**天然不冲突**。
合并方式：把两份 `questions.jsonl` 拼起来后按 `question_id` 去重（后导出的覆盖先导出的）。
注意 `schema_version` 必须一致；不一致先升级旧数据。

## 版本约定

- 本技能遵循语义化版本：`MAJOR.MINOR.PATCH`。
- `schema_version` 独立演进：加字段升 minor，改字段升 major。
- 任何破坏性改动都会在 `CHANGELOG.md` 写明迁移方式。
