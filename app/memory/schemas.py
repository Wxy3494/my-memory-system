from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", mode="before")
    @classmethod
    def valid_text(cls, value):
        # PostgreSQL text cannot store NUL, and JSON can contain lone surrogates.
        if isinstance(value, str):
            if "\x00" in value:
                raise ValueError("NUL is not supported")
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                raise ValueError("invalid Unicode") from None
        return value


class Message(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)
    timestamp: int | None = Field(default=None, ge=0, le=9223372036854775807)

    @field_validator("content")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("content must contain text")
        return value


class AddRequest(StrictModel):
    request_id: str = Field(min_length=1, max_length=512)
    user_id: str = Field(min_length=1, max_length=512)
    session_id: str = Field(min_length=1, max_length=512)
    messages: list[Message] = Field(min_length=1)

    @field_validator("request_id", "user_id", "session_id")
    @classmethod
    def identifier_bytes(cls, value):
        if len(value.encode()) > 512:
            raise ValueError("identifier exceeds 512 UTF-8 bytes")
        return value


class AddResponse(StrictModel):
    success: Literal[True] = True
    request_id: str
    user_id: str
    session_id: str


class SearchRequest(StrictModel):
    query: str = Field(min_length=1)
    user_id: str = Field(min_length=1, max_length=512)
    top_k: int = Field(ge=1, le=1000)
    options: list[str] | None = None

    @field_validator("user_id")
    @classmethod
    def identifier_bytes(cls, value):
        return AddRequest.identifier_bytes(value)

    @field_validator("options")
    @classmethod
    def valid_options(cls, value):
        if value is not None:
            for option in value:
                cls.valid_text(option)
        return value

    @field_validator("query")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("query must contain text")
        return value


class Source(StrictModel):
    message_id: str
    session_id: str
    request_id: str
    ordinal: int
    role: str
    timestamp: int | None
    start_offset: int
    end_offset: int


class Evidence(StrictModel):
    id: str
    content: str = Field(min_length=1)
    score: float = Field(allow_inf_nan=False)
    sources: list[Source]


class SearchResponse(StrictModel):
    data: list[Evidence]
