"""Small, dependency-light statistics for the eval reports."""

import math
import re
from collections.abc import Sequence


def _ranks(xs: Sequence[float]) -> list[float]:
    """Average ranks (ties share the mean of their positions), 1-based."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def pearson(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) != len(y) or len(x) < 3:
        return None
    mx, my = sum(x) / len(x), sum(y) / len(y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return None  # a constant series has no rank correlation
    return sxy / math.sqrt(sxx * syy)


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Spearman's rho (Pearson on average ranks, so ties are handled). None if undefined."""
    return pearson(_ranks(x), _ranks(y))


def mae(x: Sequence[float], y: Sequence[float]) -> float | None:
    if not x:
        return None
    return sum(abs(a - b) for a, b in zip(x, y, strict=True)) / len(x)


def stdev(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((v - m) ** 2 for v in xs) / (len(xs) - 1))


def percentile(xs: Sequence[float], p: float) -> float | None:
    """Linear-interpolated percentile, p in 0..100."""
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


_UNITS = {w: i for i, w in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
)}
_TENS = {w: 10 * i for i, w in enumerate(["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]) if i >= 2}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}


def _spelled_numbers_to_digits(text: str) -> str:
    """'five hundred and twelve' -> '512', so a reference and a transcript that differ only in how a number
    is written don't count as word errors (the usual WER normalization, as in Whisper's own evals)."""
    out: list[str] = []
    total = current = 0
    in_number = pending_and = False

    def flush() -> None:
        nonlocal total, current, in_number, pending_and
        if in_number:
            out.append(str(total + current))
            if pending_and:
                out.append("and")
        total = current = 0
        in_number = pending_and = False

    for word in text.split():
        if word in _UNITS or word in _TENS:
            current += _UNITS.get(word, 0) + _TENS.get(word, 0)
            in_number, pending_and = True, False
        elif word in _SCALES and in_number:
            scale = _SCALES[word]
            if scale == 100:
                current = max(current, 1) * 100
            else:
                total += max(current, 1) * scale
                current = 0
            pending_and = False
        elif word == "and" and in_number:
            pending_and = True  # "five hundred and twelve"; kept as a word if no number follows
        else:
            flush()
            out.append(word)
    flush()
    return " ".join(out)


def normalize_transcript(text: str) -> str:
    """For WER: lowercase, drop punctuation (keeping intra-word '), split hyphens, spelled numbers -> digits."""
    text = text.lower().replace("-", " ")
    text = re.sub(r"[^\w\s']", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return _spelled_numbers_to_digits(text)


def word_errors(reference: str, hypothesis: str) -> tuple[int, int]:
    """(edit distance in words, reference word count) after normalization; corpus WER = sum(err) / sum(n)."""
    import jiwer

    ref, hyp = normalize_transcript(reference), normalize_transcript(hypothesis)
    if not ref:
        return (len(hyp.split()), 0)
    out = jiwer.process_words(ref, hyp)
    return out.substitutions + out.deletions + out.insertions, len(ref.split())
