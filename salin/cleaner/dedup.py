"""Collapse the rolling word overlap that auto-generated captions repeat."""

from __future__ import annotations


def sanitize_word(word: str) -> str:
    """Fast alnum-only lowercase compare key (no regex)."""
    return "".join(c.lower() for c in word if c.isalnum())


def _matching_overlap(tail: list[str], head: list[str]) -> int:
    """
    Length of the longest overlap between the end of ``tail`` and the start of
    ``head``, where tokens are compared by :func:`sanitize_word` so punctuation
    and casing differences don't break a match.

    Tokens that sanitize to an empty string (punctuation-only, e.g. ``"..."``)
    never take part in a match. Comparing them literally would let two
    unrelated punctuation tokens compare equal and merge unrelated blocks.
    """
    for size in range(min(len(tail), len(head)), 0, -1):
        pairs = zip(tail[-size:], head[:size], strict=True)
        if all(
            tail_key and head_key and tail_key == head_key
            for tail_key, head_key in pairs
        ):
            return size
    return 0


def deduplicate_blocks(blocks: list[str]) -> str:
    """Merge parsed caption blocks into one deduplicated transcript."""
    final_words: list[str] = []

    for block in blocks:
        block_words = block.split()
        if not block_words:
            continue

        if not final_words:
            final_words = block_words
            continue

        # Bounding strictly by the shorter list size.
        # Capping this by a small constant prevented any duplicate longer
        # than that constant from being matched.
        window = min(len(final_words), len(block_words))
        clean_tail = [sanitize_word(w) for w in final_words[-window:]]
        clean_head = [sanitize_word(w) for w in block_words[:window]]

        final_words.extend(block_words[_matching_overlap(clean_tail, clean_head) :])

    return " ".join(final_words)
