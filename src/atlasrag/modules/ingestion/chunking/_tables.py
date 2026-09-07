import re
from dataclasses import dataclass

from atlasrag.contracts.chunking import TextTokenizer

from ._common import token_windows

_SEPARATOR_ROW_PATTERN = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")
_CELL_DELIMITER = "|"


@dataclass(frozen=True, slots=True)
class TablePart:
    content: str
    header_repeated: bool


@dataclass(frozen=True, slots=True)
class _TableLayout:
    header: tuple[str, ...]
    rows: tuple[str, ...]


def split_table(
    text: str,
    *,
    tokenizer: TextTokenizer,
    max_tokens: int,
    overlap_tokens: int,
) -> tuple[TablePart, ...]:
    if tokenizer.count_tokens(text) <= max_tokens:
        return (TablePart(content=text, header_repeated=False),)

    layout = _parse_layout(text)
    if layout is None:
        return _token_parts(
            text,
            tokenizer=tokenizer,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )

    header_text = "\n".join(layout.header)
    budget = max_tokens - tokenizer.count_tokens(header_text)
    if budget < 1:
        return _token_parts(
            text,
            tokenizer=tokenizer,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )

    return tuple(
        TablePart(content=f"{header_text}\n{body}", header_repeated=True)
        for body in _pack_rows(
            layout.rows,
            tokenizer=tokenizer,
            budget=budget,
            overlap_tokens=min(overlap_tokens, budget - 1),
        )
    )


def _pack_rows(
    rows: tuple[str, ...],
    *,
    tokenizer: TextTokenizer,
    budget: int,
    overlap_tokens: int,
) -> list[str]:
    bodies: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for row in rows:
        row_tokens = tokenizer.count_tokens(row)
        if row_tokens > budget:
            if current:
                bodies.append("\n".join(current))
                current = []
                current_tokens = 0
            bodies.extend(
                _window_texts(
                    row,
                    tokenizer=tokenizer,
                    max_tokens=budget,
                    overlap_tokens=overlap_tokens,
                )
            )
            continue

        if current and current_tokens + row_tokens > budget:
            bodies.append("\n".join(current))
            current = []
            current_tokens = 0

        current.append(row)
        current_tokens += row_tokens

    if current:
        bodies.append("\n".join(current))
    return bodies


def _token_parts(
    text: str,
    *,
    tokenizer: TextTokenizer,
    max_tokens: int,
    overlap_tokens: int,
) -> tuple[TablePart, ...]:
    return tuple(
        TablePart(content=content, header_repeated=False)
        for content in _window_texts(
            text,
            tokenizer=tokenizer,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )
    )


def _window_texts(
    text: str,
    *,
    tokenizer: TextTokenizer,
    max_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    segments = tokenizer.split_tokens(text)
    return [
        "".join(segments[start:end]).strip()
        for start, end in token_windows(
            len(segments),
            max_tokens=max_tokens,
            overlap_tokens=min(overlap_tokens, max_tokens - 1),
        )
    ]


def _parse_layout(text: str) -> _TableLayout | None:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2 or _CELL_DELIMITER not in lines[0]:
        return None

    if _SEPARATOR_ROW_PATTERN.match(lines[1]):
        header = tuple(lines[:2])
        rows = tuple(lines[2:])
    else:
        header = (lines[0],)
        rows = tuple(lines[1:])

    return _TableLayout(header=header, rows=rows) if rows else None


__all__ = ["TablePart", "split_table"]
