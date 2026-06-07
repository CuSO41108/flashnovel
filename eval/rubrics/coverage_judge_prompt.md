# Coverage Judge Prompt

你是小说生成任务覆盖率评测员。请只评估生成章节是否完成用户目标和 oracle，不评估文学风格。

你只输出 JSON，不要输出解释、Markdown 或额外文本。

输入：

故事前提：
{{story}}

故事记忆：
{{seed_memory}}

用户目标：
{{prompt}}

必须覆盖：
{{must_cover}}

禁止出现：
{{must_not}}

生成章节：
{{chapter_text}}

评测规则：

- 对 `must_cover` 中每一项给出 `hit: true/false`。
- 如果目标被隐含满足，`hit` 可以为 `true`，但 `evidence` 必须指出正文证据。
- 对 `must_not` 中每一项判断是否命中违规。
- `coverage_score = 命中的 must_cover 数量 / must_cover 总数`。
- `final_verdict` 取值：`pass` / `fail` / `needs_review`。
- 只输出 JSON。

输出 JSON 格式：

```json
{
  "coverage_score": 0.0,
  "must_cover_results": [
    {
      "item": "string",
      "hit": false,
      "evidence": "string"
    }
  ],
  "missed_must_cover": [],
  "must_not_results": [
    {
      "item": "string",
      "violated": false,
      "evidence": "string"
    }
  ],
  "contradiction_count": 0,
  "final_verdict": "needs_review"
}
```
