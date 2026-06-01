"""Prompt templates used by the novel generation tools."""

from __future__ import annotations

import string
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.llm.client import ChatMessage


@dataclass(frozen=True)
class PromptTemplate:
    """Simple strict `.format` based chat prompt template."""

    name: str
    system: str
    user: str
    response_format: str | None = None

    @property
    def variables(self) -> set[str]:
        formatter = string.Formatter()
        names: set[str] = set()
        for template in (self.system, self.user):
            for _, field_name, _, _ in formatter.parse(template):
                if not field_name:
                    continue
                names.add(field_name.split(".", 1)[0].split("[", 1)[0])
        return names

    def render(self, values: Mapping[str, Any] | None = None, **kwargs: Any) -> list[ChatMessage]:
        merged: dict[str, Any] = {}
        if values:
            merged.update(values)
        merged.update(kwargs)
        missing = self.variables.difference(merged)
        if missing:
            missing_text = ", ".join(sorted(missing))
            raise KeyError(f"missing prompt variables for {self.name}: {missing_text}")
        return [
            ChatMessage(role="system", content=self.system.format(**merged)),
            ChatMessage(role="user", content=self.user.format(**merged)),
        ]


PLAN_CHAPTER_PROMPT = PromptTemplate(
    name="plan_chapter",
    response_format="json_object",
    system=(
        "你是长篇小说章节规划助手。必须维护连续性、人物动机和伏笔账本，"
        "输出结构化 JSON，不要输出额外解释。"
    ),
    user=(
        "故事 ID: {story_id}\n"
        "章节: {chapter}\n"
        "章节目标: {chapter_goal}\n"
        "上下文包(JSON):\n{context_json}\n\n"
        "请生成章节计划 JSON，字段包括 title、beats、pov、setting、conflicts、"
        "memory_targets、continuity_notes。"
    ),
)


DRAFT_CHAPTER_PROMPT = PromptTemplate(
    name="draft_chapter",
    system=(
        "你是长篇小说写作助手。根据章节计划写正文，保持既有设定、语气和节奏，"
        "不要解释写作过程。"
    ),
    user=(
        "故事 ID: {story_id}\n"
        "章节: {chapter}\n"
        "章节计划(JSON):\n{plan_json}\n\n"
        "上下文包(JSON):\n{context_json}\n\n"
        "写作约束: {draft_instructions}\n\n"
        "请输出本章正文。"
    ),
)


EXTRACT_MEMORY_PROMPT = PromptTemplate(
    name="extract_memory",
    response_format="json_object",
    system=(
        "你是小说记忆抽取器。只抽取会影响后续章节的事实、人物状态、关系变化、"
        "伏笔、时间线和连续性约束，输出结构化 JSON。"
    ),
    user=(
        "故事 ID: {story_id}\n"
        "章节: {chapter}\n"
        "章节正文:\n{draft_text}\n\n"
        "请输出 JSON，字段包括 summary、key_events、timeline_events、relationships、"
        "foreshadows、state_changes。timeline_events 每项包含 event、participants、location；"
        "relationships 每项包含 source、target、relation；foreshadows 每项包含 key、description、action；"
        "state_changes 每项包含 entity、field、old_value、new_value、reason。"
    ),
)


CHECK_CONSISTENCY_PROMPT = PromptTemplate(
    name="check_consistency",
    response_format="json_object",
    system=(
        "你是小说连续性审校器。比较上下文记忆与章节正文，找出事实冲突、时间线错误、"
        "人物行为不一致和未解释的设定漂移，输出 JSON。"
    ),
    user=(
        "故事 ID: {story_id}\n"
        "章节: {chapter}\n"
        "上下文包(JSON):\n{context_json}\n\n"
        "章节正文:\n{draft_text}\n\n"
        "请输出 JSON，字段包括 verdict(pass 或 rewrite)、issues、blocking_issues、notes。"
    ),
)


REVIEW_CHAPTER_PROMPT = PromptTemplate(
    name="review_chapter",
    response_format="json_object",
    system=(
        "你是小说主编。评审章节是否达到章节目标、是否可读、是否满足连续性要求。"
        "输出 JSON，不要输出额外解释。"
    ),
    user=(
        "故事 ID: {story_id}\n"
        "章节: {chapter}\n"
        "rewrite_count: {rewrite_count}\n"
        "max_rewrites: {max_rewrites}\n"
        "章节计划(JSON):\n{plan_json}\n\n"
        "连续性检查(JSON):\n{consistency_json}\n\n"
        "章节正文:\n{draft_text}\n\n"
        "请输出 JSON，字段包括 verdict(accept 或 rewrite)、strengths、issues、"
        "rewrite_instructions。"
    ),
)


REWRITE_CHAPTER_PROMPT = PromptTemplate(
    name="rewrite_chapter",
    system=(
        "你是长篇小说改稿助手。只根据评审意见修订正文，保持已通过的设定和场景目标，"
        "不要输出解释。"
    ),
    user=(
        "故事 ID: {story_id}\n"
        "章节: {chapter}\n"
        "rewrite_count: {rewrite_count}\n"
        "max_rewrites: {max_rewrites}\n"
        "上下文包(JSON):\n{context_json}\n\n"
        "原正文:\n{draft_text}\n\n"
        "评审报告(JSON):\n{review_json}\n\n"
        "请输出修订后的完整章节正文。"
    ),
)


PROMPTS: dict[str, PromptTemplate] = {
    template.name: template
    for template in (
        PLAN_CHAPTER_PROMPT,
        DRAFT_CHAPTER_PROMPT,
        EXTRACT_MEMORY_PROMPT,
        CHECK_CONSISTENCY_PROMPT,
        REVIEW_CHAPTER_PROMPT,
        REWRITE_CHAPTER_PROMPT,
    )
}
