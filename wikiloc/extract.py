"""Reference extraction from whole-article wikitext (optional dependency).

:func:`extract_references` splits an article's wikitext into per-citation
reference records; pair it with :func:`resolve_references` (or just use
:func:`parse_article`). It is the same extraction the study pipeline runs.

``mwparserfromhell`` is imported lazily, so the rest of the package remains
dependency-free; this module only needs it when actually extracting.
"""

import re
from typing import Any, Dict, List

from .constants import HARV_TEMPLATES
from .parser import resolve_references


def extract_references(wikitext: str) -> List[Dict[str, Any]]:
    """Extract citation references from an article's wikitext.

    Returns a list of reference records, each with the minimal fields the
    resolver needs: ``ref_kind``, ``ref_contents`` (the locator-bearing
    content), ``ref_rp_raw``, ``ref_name`` and ``ref_self_closing``.

    A ``{{rp|…}}`` immediately following a ``<ref>`` tag (whitespace allowed)
    is attached to it and ``ref_kind`` becomes ``'ref_tag+rp'``; dangling
    ``{{rp}}`` templates are skipped. Requires ``mwparserfromhell``.
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

    pending_ref_index: int = -1
    pending_can_attach_rp = False

    def clear_pending() -> None:
        nonlocal pending_ref_index, pending_can_attach_rp
        pending_ref_index = -1
        pending_can_attach_rp = False

    for node in getattr(wikicode, "nodes", []) or []:
        # Whitespace (and HTML comments) between a <ref> and a following {{rp}}
        # keeps the window open; an HTML comment is a common editing artifact
        # and is transparent to the adjacency (WL-6).
        if pending_can_attach_rp and isinstance(node, (Text, Comment)):
            if isinstance(node, Comment) or str(node).strip() == "":
                continue
            clear_pending()

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
            pending_can_attach_rp = True
            continue

        if isinstance(node, Template):
            name_norm = _norm_template_name(str(getattr(node, "name", "")).strip())

            if name_norm == "rp":
                if pending_can_attach_rp and pending_ref_index >= 0:
                    items[pending_ref_index]["ref_kind"] = "ref_tag+rp"
                    items[pending_ref_index]["ref_rp_raw"] = str(node)
                    clear_pending()
                # Dangling {{rp}} (not attached to a preceding ref) is skipped.
                continue

            if name_norm == "r":
                raw = str(node)
                items.append(
                    {
                        "ref_kind": "r_template",
                        "ref_contents": raw,
                        "ref_rp_raw": None,
                        "ref_name": template_params(node).get("1"),
                        "ref_self_closing": False,
                    }
                )
                clear_pending()
                continue

            if name_norm == "sfn":
                raw = str(node)
                items.append(
                    {
                        "ref_kind": "sfn_template",
                        "ref_contents": raw,
                        "ref_rp_raw": None,
                        "ref_name": template_params(node).get("1"),
                        "ref_self_closing": False,
                    }
                )
                clear_pending()
                continue

            if name_norm == "sfnp":
                raw = str(node)
                items.append(
                    {
                        "ref_kind": "sfnp_template",
                        "ref_contents": raw,
                        "ref_rp_raw": None,
                        "ref_name": template_params(node).get("1"),
                        "ref_self_closing": False,
                    }
                )
                clear_pending()
                continue

            # Harvard author–date short-cite family — standalone inline short
            # footnotes (like sfn), carrying page locators.
            if name_norm in HARV_TEMPLATES:
                raw = str(node)
                items.append(
                    {
                        "ref_kind": "harv_template",
                        "ref_contents": raw,
                        "ref_rp_raw": None,
                        "ref_name": None,
                        "ref_self_closing": False,
                    }
                )
                clear_pending()
                continue

        # Any other node breaks the rp-adjacency window.
        if pending_can_attach_rp:
            clear_pending()

    return items


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
