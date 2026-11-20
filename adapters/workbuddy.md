# WorkBuddy 接法

## 安装

```bash
python3 bin/install.py
# 或手动：把整个目录复制到 ~/.workbuddy/skills/ielts-practice-export/
```

安装后重开一个会话，技能列表里会出现 `ielts-practice-export`。判断是否装好：

```bash
ls ~/.workbuddy/skills/ielts-practice-export/SKILL.md
```

## 触发方式

用户说「导出我的雅思数据」「把阅读听力作文整理成结构化数据」「分析我的错题」「剑雅全库答案库」时触发。
也可以显式喊技能名。

## 工具映射

| 技能里的动作 | WorkBuddy 工具 |
|---|---|
| 跑导出 | Bash / PowerShell（`python3 scripts/export.py ...`） |
| 读 summary | Read（`summary.md`） |
| 查字段定义 | Read（`schema/field-dictionary.md`） |
| 校验 | Bash（`python3 scripts/validate.py`） |
| 展示产物 | present_files（把 `summary.md` 或整个目录给用户） |

## 注意

- WorkBuddy 的 Bash 是 Git Bash：路径用 `/e/...` 或 `E:/...` 都行，别用反斜杠。
- 中文路径要加引号。
- 长任务（`--include-undone` 全库）用后台运行，别卡在前台超时。
- 不要把 cookie 写进会话可见的命令行历史里：优先用 `--cookie-file` 或环境变量。

## 与另一个技能的分工

同目录下可能还有 `xxgg-ielts-answer-export`（九分学长机考平台）。两者数据源不同、账号不互通：

| 技能 | 平台 | 数据 |
|---|---|---|
| `ielts-practice-export` | idictation.cn（网页） | 剑雅阅读/听力/写作 + 原文解析 |
| `xxgg-ielts-answer-export` | 九分学长桌面客户端 | 机考作答 + 错词本 + 拼写 |

用户如果两边都练过，可以分别导出；本技能的 schema 是独立的，不要混用字段名。
