"""Second line of defence for the index-level rule (ADR-019): scan rendered text.

The report model never holds index levels (by construction). This guard checks every string
the PDF renders against the index levels of the day, the previous day and the trade date
(including strikes, which are trade-date levels times a percentage), in the forms a number
would be printed with decimals: ``6176.06``, ``6,176.06``, ``6176.1``, ``6,176.1``.

Integer renderings (``6,176``) are not checked at run time: an EUR amount can legitimately
coincide with a rounded index level, and a false alarm would block the daily report. The
tests check integer forms too, on synthetic levels chosen not to collide.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


class IndexLevelLeakError(RuntimeError):
    """A rendered string contains an index level."""


def level_forms(level: float, integers: bool = False) -> set[str]:
    """Return the printed forms of ``level`` checked by the guard."""
    forms = {f"{level:.2f}", f"{level:,.2f}", f"{level:.1f}", f"{level:,.1f}"}
    if integers:
        forms |= {f"{level:.0f}", f"{level:,.0f}"}
    return forms


def find_levels(
    texts: Iterable[str], levels: Iterable[float], integers: bool = False
) -> list[tuple[str, str]]:
    """Return (form, text) pairs for every forbidden form found in ``texts``.

    Forms are matched as whole numeric tokens: "8233" inside "48233.12" is not a match.
    """
    forms = sorted({f for lv in levels for f in level_forms(lv, integers)})
    patterns = [(f, re.compile(rf"(?<![\d.,]){re.escape(f)}(?![\d]|[.,]\d)")) for f in forms]
    return [(f, t) for t in texts for f, pat in patterns if pat.search(t)]


def check_no_levels(texts: Iterable[str], levels: Iterable[float]) -> None:
    """Raise :class:`IndexLevelLeakError` if any decimal form of a level is rendered."""
    hits = find_levels(list(texts), list(levels))
    if hits:
        shown = "; ".join(f"{form!r} in {text[:60]!r}" for form, text in hits[:5])
        raise IndexLevelLeakError(f"index level found in report text: {shown}")
