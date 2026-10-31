import os

from langchain_text_splitters import RecursiveCharacterTextSplitter


def estimate_tokens(text: str) -> int:
    # shortcut: four characters/token is approximate; calibrate with provider usage.
    return (len(text) + 3) // 4


def layout_limits() -> tuple[int, int]:
    minimum = int(os.environ.get("MIN_LEAF_TOKENS", "256"))
    split = int(os.environ.get("SPLIT_TOKENS", "4096"))
    if not 0 < minimum <= split:
        raise ValueError("require 0 < MIN_LEAF_TOKENS <= SPLIT_TOKENS")
    return minimum, split


def split_text(text: str, tokens: int, overlap: int = 0) -> list[str]:
    if tokens <= 0 or not 0 <= overlap < tokens:
        raise ValueError("require 0 <= overlap < tokens")
    return RecursiveCharacterTextSplitter(
        chunk_size=tokens * 4,
        chunk_overlap=overlap * 4,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
        keep_separator=True,
        strip_whitespace=False,
    ).split_text(text)
