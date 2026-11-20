# AGENTS.md — 雅思练习数据导出

> 本文件是给 **非 WorkBuddy 宿主**（Antigravity、DeepSeek Harness、Claude Code、Cursor 等）的入口。
> 只要宿主能执行 shell 并读写文件，就能跑；不依赖任何第三方 Python 包。
> WorkBuddy 用户直接读 `SKILL.md`，内容等价。

## 你的任务

用户要「导出 / 备份 / 结构化」其在 **idictation.cn** 的雅思练习数据（阅读、听力、写作）。
你要做的是**执行本仓库的脚本**，把结果落盘并向用户汇报，而不是手工抓网页。

## 前置检查（按顺序）

1. `python3 --version` ≥ 3.8（Windows 上可能是 `python`）。没有 Python 就告知用户，不要用 curl 手工拼接口。
2. `python3 tests/selftest.py` 必须全绿。失败说明环境/编码有问题，先修再继续。
3. 确认用户已登录 idictation.cn 并能提供 `idictation_session`。

## 三条命令

```bash
# 1. 导出（默认三科，只导做过的）
python3 scripts/export.py --out ./ielts-data

# 2. 结构校验（必须通过）
python3 scripts/validate.py --in ./ielts-data

# 3. 汇报
#    读 ./ielts-data/summary.md 的前 60 行 + meta.json 的 counts/warnings
```

常用变体：

- 只导某几科：`--modules reading,listening`
- 限定套书：`--books 剑雅18,剑雅19`
- 含未做篇目（建答案库）：`--include-undone`
- 调试：`--limit 5 --dry-run`

## 登录态处理

优先级：`--cookie` > `IDICT_COOKIE` 环境变量 > `--cookie-file` > 默认路径（`~/.workbuddy/.idict_ck`、`~/.idict_ck`）。

- **不要把 cookie 写进日志、回复、提交记录。**
- 用户不知道去哪拿时，告诉他：浏览器登录 → F12 → Application/存储 → Cookies → `idictation_session`。
- 报错 `登录态失效` 就是过期了，重取即可，不要重试十次。

## 成功标准

- 退出码 0；
- `meta.json.counts.questions > 0`；
- `validate.py` 输出「通过」；
- `summary.md` 里「练习单元」数量与用户主观记忆大致相符。

若 `counts.attempts == 0`：先 `--dry-run` 看目录里 `done` 的数量，再判断是「账号没做过」还是「过滤条件太窄」，**不要直接说用户没数据**。

## 硬性约束

- **只读**：只调用查询接口，禁止任何提交/评分/重做操作。
- **仅本人账号**：用户要求导别人账号时拒绝。
- **不分发题库**：`passages.jsonl` 含版权原文，只用于本人复盘；不要上传到公开仓库或第三方服务。
- **不改 schema**：字段名与含义见 `schema/field-dictionary.md`。要加字段就加到 `extra`，不要重命名已有字段，否则跨设备数据无法合并。
- **别猜数据**：平台没有单题用时/作答轨迹，缺就是 `null`。

## 数据口径（汇报时别说错）

| 字段 | 含义 |
|---|---|
| `state` | `correct` / `wrong` / `blank`（交卷未填）/ `unattempted`（没做） |
| `is_correct` | `null` = 无作答记录，不是错 |
| `accuracy` | 0–1；站点原值（0–100）在 `accuracy_raw` |
| `q_number` | 可能是小数（23.1），排序用数值 |
| 听力判定 | 本地复算，大小写/冠词/数字写法宽容 |

## 出问题时

1. 看 `meta.json.warnings`（每条含科目 + 篇目 + 异常）。
2. 单篇复现：`--modules reading --books <书> --limit 1 --keep-raw`，看 `raw/` 里的原始响应。
3. 平台改版导致字段缺失：在 `scripts/normalize.py` 对应函数里加兜底，**保留旧字段**，再跑 `tests/selftest.py`。
4. 更细的移植说明见 `PORTING.md`。

## 目录速查

| 路径 | 作用 |
|---|---|
| `scripts/export.py` | 主程序（抓取→归一化→落盘） |
| `scripts/idict_client.py` | 接口层：签名、重试、缓存、cookie 解析 |
| `scripts/normalize.py` | 映射层：原始 JSON → 统一 schema |
| `scripts/summary.py` | 汇报层：summary.md + analysis_prompt.md |
| `scripts/validate.py` | 结构校验 |
| `tests/selftest.py` | 离线回归（合成数据，不联网） |
| `schema/field-dictionary.md` | 字段字典 |
