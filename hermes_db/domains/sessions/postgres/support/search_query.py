"""Pure bounded search grammar, shared sanitization and zero-hit relaxation."""

from dataclasses import dataclass
import re

from hermes_state_search import SessionSearchMixin


@dataclass(frozen=True)
class SearchQuery:
    text: str
    groups: tuple
    cjk: bool
    relaxed: str | None

    @property
    def terms(self):
        return tuple(dict.fromkeys(term for group in self.groups for term in group if not term[2]))


def parse_query(raw):
    text = SessionSearchMixin._sanitize_fts5_query((raw or "").replace("\x00", ""))
    groups, current, negative = [], [], False
    for token in re.findall(r'"[^"]*"\*?|\S+', text):
        upper = token.upper()
        if upper == "OR":
            if current:
                groups.append(tuple(current))
                current = []
        elif upper == "NOT":
            negative = True
        elif upper != "AND":
            prefix = token.endswith("*")
            value = token.rstrip("*").strip('"').strip()
            if value:
                current.append((value, prefix, negative))
            negative = False
    if current:
        groups.append(tuple(current))
    cjk = SessionSearchMixin._contains_cjk(text)
    return SearchQuery(text, tuple(groups), cjk, None if cjk else SessionSearchMixin._or_relaxed_query(text))
