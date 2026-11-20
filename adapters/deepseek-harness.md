# DeepSeek Harness 接法

> 适用于「system prompt + 工具调用（shell / 读写文件）」形态的 agent 运行时。
> 如果你的 harness 还支持工作区文件和 AGENTS.md，优先让它读 `AGENTS.md`；否则用下面的 system prompt。

## 1. 工作区准备

把技能目录设为工作区（或工作区子目录）：

```
workspace/
├── ielts-practice-export/   ← 技能本体
└── ielts-data/              ← 产物（可写）
```

## 2. System prompt（可直接粘贴）

```text
你可以使用一个本地工具包来完成雅思练习数据的导出与结构化。

工具包路径：<ABSOLUTE_PATH>/ielts-practice-export
运行环境：Python 3.8+，无需安装第三方包。

可用命令（在工作目录下执行）：
1) python3 scripts/export.py --out ./ielts-data [--modules reading,listening,writing]
   [--books 剑雅18] [--include-undone] [--limit N] [--keep-raw] [--csv]
2) python3 scripts/validate.py --in ./ielts-data
3) python3 tests/selftest.py

规则：
- 任何导出前，先确认用户已提供 idictation_session（--cookie 或 IDICT_COOKIE）。
- 登录态只放在命令参数/环境变量里，不得回显、不得写入任何文件。
- 只执行查询类脚本；不要自己构造 HTTP 请求去调用站点接口。
- 导出后必须跑 validate.py；失败就报告错误，不要"修数据"。
- 汇报时读 summary.md 与 meta.json，说明：练习次数、题目数、正确率、告警条数。
- 不要声称平台没有的数据（单题用时、作答轨迹）存在。
- 题库原文有版权，仅用于用户本人复盘，不要上传或分发。

数据口径：
state = correct | wrong | blank（交卷未填）| unattempted（没做）
is_correct = null 表示无作答记录，不是错
accuracy 为 0-1；站点原值在 accuracy_raw
```

## 3. 工具调用映射

| 任务 | 调用 |
|---|---|
| 环境检查 | `bash: python3 --version` → `python3 tests/selftest.py` |
| 导出 | `bash: python3 scripts/export.py --out ./ielts-data ...` |
| 校验 | `bash: python3 scripts/validate.py --in ./ielts-data` |
| 读总览 | `read: ielts-data/summary.md` |
| 下钻 | `read` 指定行 / `bash: grep '"book": "剑雅18"' ielts-data/questions.jsonl` |
| 读字段定义 | `read: schema/field-dictionary.md` |

## 4. 长任务与超时

- 全库 `--include-undone`（216 篇阅读）在普通网络下 1–3 分钟。
- 若 harness 有单命令超时（常见 60s），改用分批：
  `--modules reading --books 剑雅4 --include-undone`，逐本跑。
- 缓存会保留在 `ielts-data/.cache/`，中断后重跑不会重复请求。

## 5. 常见错误对照

| 输出 | 含义 | 该怎么做 |
|---|---|---|
| exit 2 / `登录态失效` | cookie 过期 | 让用户重新复制 `idictation_session` |
| exit 3 / `请求失败` | 网络不通 | 检查网络/代理，`--workers 1` 重试 |
| exit 4 / attempts=0 | 没做过或过滤太窄 | `--dry-run` 看 done 数，别断言用户没数据 |
| `validate.py` 失败 | 数据/代码不一致 | 保留产物，报告具体行号，跑 selftest 复现 |

## 6. 不要做的事

- 不要把 `questions.jsonl` 整份读进上下文（几百 KB 起步），先 `summary.md`。
- 不要修改 `schema_version` 或字段名来"适配"下游；下游应该适配 schema。
- 不要在 system prompt 里写死 cookie。
