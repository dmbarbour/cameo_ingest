"""Windows of text as the production stack cuts them: chunks of about 512 tokens that overlap
their neighbours (plan RE, decision 1). The stack's own splitter is unknown, so this cuts on the
embedding model's tokens, and keeps each window a substring of the text."""

from __future__ import annotations

SPECIAL = 2  # the [CLS] and [SEP] (or <s> and </s>) tokens a model adds to every input


def windows_by_offsets(text: str, offsets: list[tuple[int, int]], size: int = 512, overlap: int = 64) -> list[str]:
    """`text` cut into windows of at most `size` tokens (special tokens included), each starting
    `overlap` tokens before the previous one ends. `offsets` are the character spans of the
    text's tokens, without special tokens."""
    body = size - SPECIAL
    if not 0 <= overlap < body:
        raise ValueError(f"overlap {overlap} must be at least 0 and less than {body}")
    if len(offsets) <= body:
        return [text]
    out = []
    start = 0
    while True:
        end = min(len(offsets), start + body)
        out.append(text[offsets[start][0]:offsets[end - 1][1]])
        if end == len(offsets):
            return out
        start = end - overlap


def windows(text: str, model_name: str, size: int = 512, overlap: int = 64) -> list[str]:
    """`windows_by_offsets` with the model's own tokenizer."""
    from .embed import tokenizer

    tok = tokenizer(model_name)
    tok.no_truncation()
    return windows_by_offsets(text, tok.encode(text, add_special_tokens=False).offsets, size, overlap)
