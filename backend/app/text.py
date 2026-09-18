"""Counting things in plain English, in one place.

Wording that a person reads is written once and used everywhere: a finding, a workflow step, a
readiness reason and an assistant answer all count the same way. "1 document", never
"1 document(s)" and never "1 documents".
"""

from __future__ import annotations


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    """"1 document" / "2 documents"."""
    return f"{count} {singular if count == 1 else (plural_form or singular + 's')}"


class Counted(int):
    """A number that knows how to name what it counts, for use in a wording template.

    `"{source_count:document}".format_map(context)` renders "1 document" or "3 documents", so the
    rules keep their own wording in `rules.yaml` and still read correctly at any count. Written
    without a format spec it is just the number, as any integer is. An irregular plural is given
    after a slash: `{count:entry/entries}`.
    """

    def __format__(self, spec: str) -> str:
        if not spec:
            return str(int(self))
        singular, _, irregular = spec.partition("/")
        return plural(int(self), singular, irregular or None)
