# 字段字典 · schema v1.0

所有 JSONL 都是「一行一个 JSON 对象」，UTF-8，无 BOM。字段名固定为 snake_case，跨设备/跨版本保持稳定。

## 通用约定

| 约定 | 说明 |
|---|---|
| `schema_version` | 固定 `"1.0"`；每行都有，方便混入旧数据时识别 |
| `module` | `reading` \| `listening` \| `writing` |
| 缺失值 | 一律 `null`，不用 `""` / `0` / `"N/A"` 代替 |
| 时间 | 提交时间保留站点原样（UTC 字符串，形如 `2026-11-03T11:16:42.000000Z`） |
| 用时 | 秒（整数）；展示用 `duration_text`（`m:ss`） |
| 正确率 | `0–1` 浮点；站点原值（0–100）在 `accuracy_raw` |
| ID | `module:part_id[:result_id]`，可跨次导出稳定重建 |

### 实体关系

```
catalog.jsonl ──part_id──┐
                         ├──> passages.jsonl.passage_id
attempts.jsonl ──attempt_id──> questions.jsonl.attempt_id
      │                        │
      └──passage_id────────────┘
                               └──group_id──> groups.jsonl.group_id
writing.jsonl  （独立，无外键）
```

---

## catalog.jsonl

一行一个练习单元（含没做过的），用来回答「我做过什么 / 还剩什么 / 全库有多少」。

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | string | `"1.0"` |
| `module` | enum | 科目 |
| `source` | string\|null | `jianya` / `g` / `jijing` / `zhenti` |
| `book` | string\|null | 套书，如 `剑雅18` |
| `test` | string\|null | `Test 1` |
| `part` | string\|null | `Passage 2` / `Part 3` / 写作题目名 |
| `part_index` | int\|null | 从标题解析出的序号（1 起） |
| `part_id` | int | 练习单元 ID（阅读=篇，听力=Part，写作=paper） |
| `test_id` | int\|null | 听力/阅读的 Test ID |
| `done` | bool | 是否有作答记录 |
| `accuracy` | float\|null | 0–1 |
| `duration_sec` | int\|null | 用时 |
| `question_range` | string\|null | `Q1-13` / `1-10` |
| `question_types` | string[] | 站点给的题型标签（中文，原样） |
| `topics` | string[] | 站点给的话题标签 |
| `total_num` | int\|null | 题目数 |
| `kind` | string\|null | 写作专用：`dazuowen` / `xiaozuowen` |

---

## attempts.jsonl

一行一次提交。阅读=一篇；听力=一个 Part；写作不写这里（见 `writing.jsonl`）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | string | |
| `attempt_id` | string | `reading:2102:13026511` / `listening:2161:20160865` |
| `module` | enum | |
| `book` / `test` / `part` | string\|null | 定位 |
| `part_index` | int\|null | 阅读 1–3；听力 1–4 |
| `passage_id` | string\|null | 关联 `passages.jsonl` |
| `result_id` | int\|null | 站点提交记录 ID（重复刷题时每次不同） |
| `user_id` | int\|null | 站点账号 ID（仅阅读 attempt 有） |
| `title` | string\|null | 阅读文章标题 / 听力 `书 Test` |
| `submitted_at` | string\|null | 提交时间 |
| `duration_sec` | int\|null | 用时 |
| `duration_text` | string\|null | `23:47` |
| `accuracy` | float\|null | 按题复算的 0–1 正确率 |
| `accuracy_raw` | int\|null | 站点 `zhengquelv`（0–100） |
| `correct` / `wrong` / `blank` / `total` / `answered` | int | 计数；`blank` = 交卷未填 |
| `action` | string\|null | 站点提交方式（`手动提交`） |
| `question_range` | string\|null | 覆盖题号 |
| `question_types` | string[] | 本单元的题型（中文） |
| `topics` | string[]\|null | 话题标签 |
| `by_type` | object[] | `{question_type, question_type_zh, correct, total, accuracy}` |
| `marks` | object | `{highlights[], notes[], highlight_count}` |
| `vocab_stats` | object\|null | 听力专用：目标分、目标正确率、错词本 |
| `history` | object[] | 同单元的历史提交（重复刷题），含 `result_id/label/is_current` |

### marks.highlights[]

| 字段 | 说明 |
|---|---|
| `text` | 高亮文本 |
| `level` | 1 主高亮 / 2 次高亮 |
| `scope` | `article`（原文）/ `question`（题干） |
| `paragraph` | 定位到的段落字母（原文高亮） |
| `char` | 段内字符偏移 |
| `question_number` | 题干高亮命中的题号 |
| `before` / `after` | 前后各 30 字符，便于核对 |

---

## questions.jsonl（分析主力）

一行一道题。**阅读与听力共用同一套字段**。

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | string | |
| `question_id` | string | `reading:2102:40206` / `listening:2161:21955` |
| `attempt_id` | string\|null | 关联 attempts；`null` = 没做过（答案库模式） |
| `module` | enum | |
| `book` / `test` / `part` | string\|null | 定位 |
| `part_index` | int\|null | |
| `group_id` | string | 关联 `groups.jsonl` |
| `question_type` | string | 稳定英文 key，见下表 |
| `question_type_zh` | string | 中文名 |
| `question_type_raw` | int\|null | 站点原始 type 码（仅排错用） |
| `q_number` | int\|float\|null | 数值题号，排序用它 |
| `q_number_raw` | string | 原始题号字符串 |
| `stem` | string | 题干（三种存法已归一） |
| `stem_source` | enum | `title` / `collect` / `table` / `group_title` / `instruction` / `empty` |
| `options` | object[] | `{key, text}`；多选题自动继承组内共享选项 |
| `yours` | string\|null | 我的答案；听力多选为 `"A, B"` |
| `correct_answer` | string | 官方答案（多解用 `,` 或 `/` 分隔，原样） |
| `accepted_answers` | string[] | 拆开后的可接受答案 |
| `is_correct` | bool\|null | `null` = 无作答记录 |
| `state` | enum | `correct` / `wrong` / `blank` / `unattempted` |
| `error_tags` | string[] | 用户自标错因（阅读 `reports`），非官方 |
| `error_note` | string\|null | 自标错因的备注（常见为错填的词） |
| `note` | string | 用户在该题写的笔记 |
| `evidence` | object | 见下 |
| `extra` | object\|null | 放不进主字段的原始信息 |

### state 的四种取值（最容易误读）

| state | 含义 | 分析含义 |
|---|---|---|
| `correct` | 答对 | — |
| `wrong` | 答错 | 能力/方法问题 |
| `blank` | 交卷但没填 | 时间分配、策略问题 |
| `unattempted` | 根本没过这题（没做过的篇目） | 不能计入能力统计 |

### question_type 取值

| key | 中文 | 典型指令 |
|---|---|---|
| `tfng` | 判断题(T/F/NG) | TRUE / FALSE / NOT GIVEN |
| `ynng` | 判断题(Y/N/NG) | YES / NO / NOT GIVEN |
| `mcq_single` | 单选 | Choose the correct letter |
| `mcq_multi` | 多选 | Choose TWO/THREE letters |
| `matching_paragraph` | 段落信息匹配 | Which paragraph contains… |
| `matching_heading` | 标题匹配 | Choose the correct heading |
| `matching_feature` | 人物/特征匹配 | Match each statement with the correct researcher |
| `matching_sentence_ending` | 句子结尾匹配 | Complete each sentence with the correct ending |
| `matching_other` | 其它匹配 | Match… |
| `completion_note` | 笔记填空 | Complete the notes |
| `completion_table` | 表格填空 | Complete the table |
| `completion_form` | 表单填空 | Complete the form |
| `completion_summary` | 摘要填空 | Complete the summary |
| `completion_sentence` | 句子填空 | Complete the sentences |
| `completion_flowchart` | 流程图填空 | flow-chart |
| `completion_diagram` | 图示填空 | Label the diagram |
| `labelling_map` | 地图/平面图标注 | Label the map |
| `short_answer` | 简答 | Answer the questions / NO MORE THAN… |
| `other` | 其它 | 未命中规则 |

> 判定顺序写在 `normalize.py::_RULES`，改规则会改变历史数据的分布，**改之前先备份**。

### evidence

| 字段 | 类型 | 说明 |
|---|---|---|
| `locating` | object[] | 官方定位词：`{locating_word, synonyms:[{synonym, sentences:[{index, paragraph, text}]}]}` |
| `key_locating` | object[] | 关键定位词（同上结构） |
| `central_sentences` | object[] | 中心句：`{index, paragraph, text, translation}` |
| `answer_sentences` | any | 答案句（听力常为时间轴对象） |
| `ai` | object\|null | `{analysis, reason, keywords, paraphrasing, confidence, location_sentence, sentences[]}` |
| `ai_analysis` | string | AI 完整解析（HTML 已清洗，保留 `【题干】【原文】【推理】` 分段） |
| `analysis_blocks` | object[] | 官方解析块：`{type, content, location}`；type 含 `answer/header/text/reference/break` |
| `option_analysis` | object[] | 听力干扰项解释：`{option, reason}`（**不是**你的错因） |
| `start_ms` / `end_ms` | int\|null | 听力：该题在音频中的位置 |

> `central_sentences[].index` 与 `passages.jsonl` 同一篇的 `sentences[].i` 同源，可直接互查。

---

## groups.jsonl

一行一个题组（共享指令或素材的一组题）。填空题的**笔记/表格原文**在这里，`questions.stem` 可能只是占位句。

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | string | |
| `group_id` | string | `reading:2102:583` |
| `attempt_id` | string\|null | |
| `module` | enum | |
| `book` / `test` / `part` / `part_index` | | 定位 |
| `question_type` / `question_type_zh` / `question_type_raw` | | 同 questions |
| `instruction` | string | 组的指令原文（已去 HTML） |
| `title` | string | 组标题；多选题的题干常在这里 |
| `body` | string | `collect` 字段（笔记类题干的 HTML 正文） |
| `table` | object\|null | 表格原文：`{content: [[...]]}` 二维数组 |
| `options` | object[] | 组内共享选项（`collect_option.list`） |
| `image_url` | string\|null | 配图 |
| `question_numbers` | int[] | 覆盖题号 |

---

## passages.jsonl

一行一篇原文/转写。

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | string | |
| `passage_id` | string | `reading:2102` / `listening:2161` |
| `module` | enum | |
| `book` / `test` / `part` / `part_index` | | 定位 |
| `title` | string\|null | 阅读文章标题；听力为 `null` |
| `lead_in` | string | 正文前的导语（`pre-A`） |
| `paragraph_source` | enum | `content`（有 A–Z）/ `sentences_only`（只有逐句）/ `transcript`（听力）/ `empty` |
| `paragraphs` | object[] | `{label, text}`；听力为空数组 |
| `sentences` | object[] | 见下 |
| `word_count` | int | 词数 |
| `audio` | object\|null | `{part_url, full_url}`（听力） |
| `extra` | object\|null | 小标题、配图、站点原始 notes 等 |

### sentences[]

| 字段 | 类型 | 说明 |
|---|---|---|
| `i` | int | 句序号，从 0 开始；与 `evidence.central_sentences[].index` 对齐 |
| `text` | string | 英文句子 |
| `translation` | string | 中文翻译 |
| `paragraph` | string | 所属段落字母；听力为 Part 标题 |
| `start_ms` / `end_ms` | int\|null | 听力时间轴 |
| `grammar` | object\|null | 语法拆解：`句型 / 主句部分{主语,谓语,宾语,表语,状语...} / 句子时态 / 语法成分[] / 语法具体知识点[]` |
| `grammar_html` | string | 带成分标注的 HTML（可能为空） |

---

## writing.jsonl

一行一篇作文。

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | string | |
| `writing_id` | string | `writing:1883484` |
| `attempt_id` | string | 与 writing_id 相同（便于统一处理） |
| `task` | enum | `task_1`（小作文）/ `task_2`（大作文） |
| `kind` / `kind_zh` | string | `xiaozuowen`/`dazuowen` + 中文 |
| `source` | string\|null | `jianya` / `jijing` / `g` |
| `book` / `test` | string\|null | 从题目名解析 |
| `paper_name` / `paper_id` | | 题目 ID 与名称 |
| `question` | object | `{text, category, image_url, image_desc}` |
| `essay` | object | `{text, word_count, duration_sec, duration_text, submitted_at}` |
| `scoring` | object | 见下 |
| `corrections` | object[] | 逐句批注（平台未返回时为空数组） |
| `corrections_done` | bool | 批改是否完成 |
| `sample_essay` | object\|null | `{title, text}` 范文 |
| `marks` | object | `{highlights, notes, result_notes}` |
| `history` | object[] | 同一题的历史提交 |
| `extra` | object | `step1_done/step2_done/step3_done` |

### scoring

```json
{
  "total_score": 6,
  "score": null,
  "corrected_at": "2026-01-02 10:02:00",
  "models": {
    "qwen": {
      "band": 6, "raw_band": 6, "intervention": null, "task_type": "task_2",
      "dimensions": [
        {"key": "task_performance", "name": "任务回应", "en_name": "TASK RESPONSE",
         "score": 6, "reason": "…", "items": [{"name": "完整回应题目", "score": 6, "reason": "…"}]}
      ]
    },
    "deepseek": {…}, "doubao": {…}
  },
  "consensus": {
    "band_mean": 6.25, "band_min": 6, "band_max": 6.5, "band_spread": 0.5,
    "models_counted": 2,
    "by_dimension": {"task_performance": 6.25, "…": 6.25}
  }
}
```

`consensus.band_spread` 是模型分歧度：>1.0 说明这篇的分数不可靠，别拿它当基准。

---

## meta.json

| 字段 | 说明 |
|---|---|
| `schema_version` | schema 版本 |
| `generator` | `{name, version}` |
| `exported_at` | 导出时间（本地时区） |
| `source` | 平台与基址 |
| `scope` | 本次范围：modules / books / include_undone / 题库来源 |
| `counts` | 各文件行数 |
| `account.user_id` | 站点账号 ID（用于确认没导错号） |
| `conventions` | 口径声明（正确率、时间、ID、state） |
| `warnings` | 非致命错误列表（哪篇、什么异常） |
| `files` | `{name, bytes, sha256}`，用于校验传输完整性 |

---

## 原始字段对照（移植用）

| 原始字段 | schema | 备注 |
|---|---|---|
| `jianya_name` / `test_name` / `title` | `book` / `test` / `part` | 原样 |
| `practice_result.zhengquelv` | `attempts.accuracy_raw` | 0–100 |
| `practice_result.duration` | `attempts.duration_sec` | 秒 |
| `practice_result.result_blanks[]` | `questions.{yours, correct_answer, is_correct}` | 阅读以此为准 |
| `practice_result.answer` | 听力作答 | JSON 字符串，`id=0` 表示整组多选 |
| `reports[blank_id]` | `questions.error_tags / error_note` | 用户自标，非官方 |
| `question[].type` | `question_type_raw` | 不要直接展示给用户 |
| `question[].desc` | `groups.instruction` | 题型判定依据 |
| `question[].collect` | `groups.body` | `$N$` 占位符 |
| `question[].table.content` | `groups.table.content` | 二维数组 |
| `question[].collect_option.list` | `groups.options` / `questions.options` | 多选共享 |
| `list[].display_answer` | `correct_answer` | 官方答案 |
| `list[].answers` | `accepted_answers` | 可能为 null |
| `list[].locating_words` | `evidence.locating` | 嵌套 `syn_ary/target_sen` |
| `list[].central_sentences` | `evidence.central_sentences` | |
| `list[].ai_analyze` | `evidence.ai_analysis` | HTML |
| `list[].wrong_reasons` | `evidence.option_analysis` | 干扰项解释，**不是**你的错因 |
| `content.A–Z` | `passages.paragraphs` | 空值要剔除 |
| `content.order_ary` | 段落顺序 | 可能为 null |
| `new_content[]` | `passages.sentences[]` | 逐句 + 翻译 + 语法 |
| `grammar_analysis[]` | `sentences[].grammar` | 与 new_content 同序 |
| `parts[].content[]` | 听力 `sentences[]` | `en_text/cn_text/start_time/end_time` |
| `parts[].content_jingting[]` | 听力 `sentences[].grammar` | 与 content 用序列对齐合并 |
| `blank_answer_word_comparison` | `attempts.vocab_stats` | 听力目标分/错词本 |
| `practice_result_history_grouped` | `attempts.history` | 含 `part_id/is_current` |
| `dazuowen_qwen_score_details` | `writing.scoring.models.qwen` | 三模型同构 |
| `corrections` / `sample_essay` | `writing.corrections / sample_essay` | |

---

## 分析时的常见误读

1. **把 `blank` 当 `wrong`**：前者是没时间填，后者是不会。合并会高估能力问题。
2. **把 `is_correct: null` 当错**：那是没做过（答案库模式），不该进正确率分母。
3. **用 `q_number_raw` 排序**：`"23.1"` 按字符串会排在 `"23"` 前面。用 `q_number`。
4. **把 `accuracy_raw` 当精确值**：站点四舍五入到整数，`accuracy` 才是按题复算的。
5. **听力 `option_analysis` 当错因**：那是官方解释干扰项为什么诱人。
6. **跨 Part 用 `sentences[].i`**：索引只在同一 `passage_id` 内有效。
7. **把 `stem_source="table"` 的题干当完整句**：它是「列名 \| 行标签 \| 单元格」拼接，完整语境看 `groups.table`。
8. **认为所有篇目都有段落**：`paragraph_source="sentences_only"` 时段落信息匹配题只能靠句意，不能靠段落标签。
