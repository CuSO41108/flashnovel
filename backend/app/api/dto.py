from __future__ import annotations

from pydantic import BaseModel, Field


class CharacterInput(BaseModel):
    name: str
    role: str = ""
    description: str = ""


class WordCountInput(BaseModel):
    min_words: int = 1200
    target_words: int = 1800
    max_words: int = 2600


class CreateStoryRequest(BaseModel):
    title: str = Field(min_length=1)
    premise: str = Field(min_length=1)
    genre: str = ""
    style: str = "default"
    characters: list[CharacterInput] = Field(default_factory=list)
    word_count: WordCountInput = Field(default_factory=WordCountInput)


class CreateRunRequest(BaseModel):
    story_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    provider: str = ""
    base_url: str = ""
    model: str = ""
    max_chapters: int = 5
    context_budget: int = 0


class ResumeRunRequest(BaseModel):
    prompt: str = ""


class ConfirmRunRequest(BaseModel):
    decision: str = "continue"
    note: str = ""


class Envelope(BaseModel):
    code: str = "OK"
    data: object


def ok(data: object) -> dict[str, object]:
    return {"code": "OK", "data": data}
