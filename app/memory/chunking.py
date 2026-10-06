"""Lossless Unicode slicing with conservative UTF-8 budgets and source offsets.

The configuration keeps the plan's TOKEN names, but uses UTF-8 byte cost rather
than claiming to reproduce the provider's tokenizer. No character is dropped.
"""
import hashlib
import json
from dataclasses import dataclass

from .config import CHUNKER_VERSION


def stable_id(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def payload_hash(request):
    return hashlib.sha256(json.dumps(request.model_dump(), sort_keys=True,
                                    ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Slice:
    start: int
    end: int
    content: str


def split_text(text, target=400, overlap=60):
    if target < 4 or not 0 <= overlap < target // 2:
        raise ValueError("invalid chunk budget")
    start = 0
    while start < len(text):
        end, cost = start, 0
        while end < len(text) and cost + len(text[end].encode("utf-8")) <= target:
            cost += len(text[end].encode("utf-8"))
            end += 1
        # Prefer a sentence/paragraph boundary in the last quarter of the slice.
        if end < len(text):
            for pos in range(end - 1, start + (end - start) * 3 // 4, -1):
                if text[pos] in "\n。！？.!?":
                    end = pos + 1
                    break
        yield Slice(start, end, text[start:end])
        if end == len(text):
            break
        next_start, cost = end, 0
        while next_start > start + 1:
            step = len(text[next_start - 1].encode("utf-8"))
            if cost + step > overlap:
                break
            next_start -= 1
            cost += step
        start = next_start


def make_chunks(request, config):
    chunks = []
    for ordinal, message in enumerate(request.messages):
        message_id = stable_id("message", request.user_id, request.request_id, ordinal)
        for piece in split_text(message.content, config.target, config.overlap):
            chunks.append(dict(
                chunk_id=stable_id("chunk", request.user_id, request.request_id, ordinal,
                                   config.signature, CHUNKER_VERSION, piece.start, piece.end),
                message_id=message_id, ordinal=ordinal, start_offset=piece.start,
                end_offset=piece.end, content=piece.content,
            ))
            if len(chunks) > config.max_chunks:
                from .errors import PayloadTooLarge
                raise PayloadTooLarge("too_many_chunks")
    return chunks
