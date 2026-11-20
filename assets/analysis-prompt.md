# 雅思练习数据 · 分析指令（模板）

> `export.py` 会基于实际数据重新生成一份 `analysis_prompt.md`；这份是静态模板，
> 适合手工粘贴到任何模型。把 `{{}}` 占位符换成实际数字即可。

你拿到的是一份雅思练习数据集，schema v1.0，由 `ielts-practice-export` 从 idictation.cn 导出。

数据规模：练习 {{ATTEMPTS}} 次、题目 {{QUESTIONS}} 道、原文/转写 {{PASSAGES}} 篇、写作 {{WRITING}} 篇。

## 读取顺序

1. `summary.md` —— 先建立全局：分科、分题型、分位置、错题清单、用时。
2. `questions.jsonl` —— 按需过滤，不要整份加载：
   - 某本书：`grep '"book": "剑雅18"' questions.jsonl`
   - 某题型：`grep '"question_type": "matching_paragraph"' questions.jsonl`
   - 错题：`grep '"state": "wrong"' questions.jsonl`
3. `passages.jsonl` —— 只在需要原文时按 `passage_id` 取。
4. `writing.jsonl` —— 写作单独读。

## 字段口径（必须遵守）

- `state`: `correct` / `wrong` / `blank`（交卷未填）/ `unattempted`（没做过）。
  **blank ≠ wrong**：前者是时间与策略，后者是能力。
- `is_correct: null` 表示没有作答记录，不是「错」。
- `accuracy` 是 0–1；站点原值（0–100）在 `accuracy_raw`，两者可能差 1 个百分点（四舍五入）。
- `q_number` 可能是小数（23.1），排序用数值。
- 听力判分是本地复算，大小写/冠词/数字写法宽容，拼写错仍算错。
- `evidence.central_sentences[].index` 指向同篇 `passages.sentences[].i`。

## 输出结构

### 1. 能力画像
按题型给正确率与题数。样本量 < 10 的只描述、不下结论。

### 2. 失分归因
把错题归到五类，每类给 2–3 个 `question_id` 作为证据：

| 类型 | 判据 |
|---|---|
| 定位失败 | 原文里找不到对应段落/句子 |
| 同义替换没认出 | 定位到了，但没把题干的词和原文的表达对应起来 |
| 词义/拼写 | 定位与替换都对，答案词写错或不懂 |
| 逻辑判断 | 判断题把 NG 当 F、把 FALSE 当 TRUE |
| 时间不够 | `state=blank` 集中出现在后段 |

### 3. 位置与套书差异
阅读 P1/P2/P3、听力 Part 1–4、各套书之间的正确率与用时差异。指出是否存在系统性洼地。

### 4. 趋势
按 `submitted_at` 排序，看正确率与用时走向；样本 ≥ 10 时可给相关系数，否则只描述。

### 5. 处方
按「收益/成本」排序，最多 3 条。每条必须给出：
- 具体练什么（题型 + 篇目，从 `catalog.jsonl` 里选没做过的）
- 完成标准（可验证，如「段落匹配 8 题错 ≤ 1」）
- 复查方式（用哪几个字段验证）

## 禁止

- 不要为凑结论忽略样本量；n < 5 只描述。
- 不要把平台没有的数据（单题用时、作答轨迹、切屏）说成「你没做」。
- 不要把 `evidence.option_analysis`（干扰项解释）当作用户的错因。
- 不要在没有原文证据时推断「同义替换没认出」。
