# 原始脚本（0.x，已被 scripts/ 取代）

这三个文件是最早的一次性脚本，逻辑已合并进 `scripts/`：

| 原文件 | 现在对应 |
|---|---|
| `IELTS_idictation_api.py` | `scripts/idict_client.py` + `scripts/normalize.py`（阅读） |
| `idictation_listening.py` | `scripts/normalize.py::listening_entities` |
| `idictation_writing.py` | `scripts/normalize.py::writing_entity` |

保留原因：字段口径的「原始证据」，平台改版时可对照新旧响应定位差异。

注意：旧脚本把 cookie 路径写死在 `C:/Users/...`，且各自 print 调试信息，**不要直接用于新环境**，请用 `scripts/export.py`。
