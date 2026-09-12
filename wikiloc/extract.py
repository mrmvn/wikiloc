"""Reference extraction from whole-article wikitext (optional dependency).

:func:`extract_references` splits an article's wikitext into per-citation
reference records; pair it with :func:`resolve_references` (or just use
:func:`parse_article`). It is the same extraction the study pipeline runs.

The walk is recursive: ``<ref>`` tags and standalone short-cite templates are
collected wherever they appear, including inside infoboxes, ``{{reflist|refs=…}}``
list-defined references and HTML tags.

``mwparserfromhell`` is imported lazily, so the rest of the package remains
dependency-free; this module only needs it when actually extracting.
"""

import re
from typing import Any, Dict, Iterator, List

from .constants import HARV_TEMPLATES
from .parser import resolve_references

# Standalone short-cite templates collected outside a <ref>, mapped to the
# ref_kind the resolver expects. Harvard variants are handled separately via
# HARV_TEMPLATES (they all collapse to 'harv').
_SHORT_CITE_KINDS = {
    "r": "r_template",
    "sfn": "sfn_template",
    "sfnp": "sfnp_template",
}


def extract_references(wikitext: str) -> List[Dict[str, Any]]:
    """Extract citation references from an article's wikitext.

    Walks the whole parse tree — ``<ref>`` tags and standalone short-cite
    templates, including ones nested inside other templates (infoboxes,
    ``{{reflist|refs=…}}`` list-defined references, navboxes) or HTML tags —
    and returns them in first-appearance (document) order.

    Returns a list of reference records, each with the minimal fields the
    resolver needs: ``ref_kind``, ``ref_contents`` (the locator-bearing
    content), ``ref_rp_raw``, ``ref_name`` and ``ref_self_closing``.

    A ``{{rp|…}}`` immediately following a ``<ref>`` tag in the *same* sibling
    sequence (whitespace and HTML comments allowed) is attached to it and
    ``ref_kind`` becomes ``'ref_tag+rp'``; dangling ``{{rp}}`` templates are
    skipped. Adjacency is evaluated per sibling sequence, so a ``{{rp}}`` after
    a template that merely *contains* a ``<ref>`` is not attached.

    The contents of a ``<ref>`` are not descended into: a short-cite inside it
    is parsed as part of that reference (not double-counted), and a ``<ref>``
    inside a ``<ref>`` is ignored. Requires ``mwparserfromhell``.
    """
    import mwparserfromhell  # type: ignore
    from mwparserfromhell.nodes import Comment, Tag, Template, Text  # type: ignore

    def template_params(tpl: Template) -> Dict[str, str]:
        params: Dict[str, str] = {}
        for p in getattr(tpl, "params", []) or []:
            key = str(getattr(p, "name", "")).strip()
            val = str(getattr(p, "value", "")).strip()
            params[key] = val
        return params

    def tag_attrs(tag: Tag) -> Dict[str, str]:
        attrs: Dict[str, str] = {}
        try:
            for a in getattr(tag, "attributes", []) or []:
                key = str(a.name).strip()
                val = str(a.value).strip() if a.value is not None else ""
                attrs[key] = val
        except Exception:
            attrs = {}
        return attrs

    wikicode = mwparserfromhell.parse(wikitext)
    items: List[Dict[str, Any]] = []

    def walk(nodes: Any) -> None:
        # ``pending_ref_index`` is local to this sibling sequence: it indexes a
        # collected <ref> that a following {{rp}} may attach to. It is never
        # carried into (or out of) a nested node.
        pending_ref_index = -1

        for node in nodes or []:
            # Whitespace (and HTML comments) between a <ref> and a following
            # {{rp}} keeps the window open; an HTML comment is a common editing
            # artifact and is transparent to the adjacency (WL-6).
            if pending_ref_index >= 0 and isinstance(node, (Text, Comment)):
                if isinstance(node, Comment) or str(node).strip() == "":
                    continue
                pending_ref_index = -1

            if isinstance(node, Tag) and str(getattr(node, "tag", "")).lower() == "ref":
                attrs = tag_attrs(node)
                items.append(
                    {
                        "ref_kind": "ref_tag",
                        "ref_contents": str(getattr(node, "contents", "") or ""),
                        "ref_rp_raw": None,
                        "ref_name": attrs.get("name"),
                        "ref_self_closing": bool(getattr(node, "self_closing", False)),
                    }
                )
                pending_ref_index = len(items) - 1
                # Do not descend into <ref> contents: short-cites inside are
                # parsed as part of that reference, and <ref> inside <ref> is
                # ignored.
                continue

            if isinstance(node, Template):
                name_norm = _norm_template_name(str(getattr(node, "name", "")).strip())

                if name_norm == "rp":
                    if pending_ref_index >= 0:
                        items[pending_ref_index]["ref_kind"] = "ref_tag+rp"
                        items[pending_ref_index]["ref_rp_raw"] = str(node)
                    # Dangling {{rp}} (not attached to a preceding ref) is skipped.
                    pending_ref_index = -1
                    continue

                kind = _SHORT_CITE_KINDS.get(name_norm)
                if kind is None and name_norm in HARV_TEMPLATES:
                    kind = "harv_template"
                if kind is not None:
                    items.append(
                        {
                            "ref_kind": kind,
                            "ref_contents": str(node),
                            "ref_rp_raw": None,
                            "ref_name": None if kind == "harv_template"
                            else template_params(node).get("1"),
                            "ref_self_closing": False,
                        }
                    )
                    pending_ref_index = -1
                    continue

            # Any other node breaks the rp-adjacency window; recurse into it so
            # nested references are still found.
            pending_ref_index = -1
            for child in _child_wikicodes(node):
                if child is not None:
                    walk(getattr(child, "nodes", []))

    walk(getattr(wikicode, "nodes", []) or [])
    return items


def _child_wikicodes(node: Any) -> Iterator[Any]:
    """Yield a node's child Wikicode objects, in reading order."""
    from mwparserfromhell.nodes import (  # type: ignore
        Argument,
        ExternalLink,
        Tag,
        Template,
        Wikilink,
    )

    if isinstance(node, Template):
        yield node.name
        for param in node.params:
            yield param.value
    elif isinstance(node, Tag):
        yield node.contents
    elif isinstance(node, Argument):
        yield node.default
    elif isinstance(node, Wikilink):
        yield node.text
    elif isinstance(node, ExternalLink):
        yield node.title


def _norm_template_name(name: str) -> str:
    """Normalize a MediaWiki template name for comparison.

    Converts to lowercase, replaces underscores with spaces, collapses
    whitespace, and strips a ``template:`` namespace prefix.
    """
    n = (name or "").strip().lower()
    n = n.replace("_", " ")
    n = re.sub(r"\s+", " ", n)
    if n.startswith("template:"):
        n = n.split(":", 1)[1].strip()
    return n


def parse_article(wikitext: str, language: str = "en") -> list:
    """Extract and resolve every reference in an article's wikitext.

    Convenience wrapper: :func:`extract_references` then
    :func:`resolve_references`. Requires ``mwparserfromhell`` (see the
    ``extract`` extra in pyproject.toml).
    """
    return resolve_references(extract_references(wikitext), language=language)
