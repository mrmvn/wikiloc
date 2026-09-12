"""Reference extraction from whole-article wikitext (optional dependency).

:func:`extract_references` splits an article's wikitext into per-citation
reference records; pair it with :func:`resolve_references` (or just use
:func:`parse_article`). It is the same extraction the study pipeline runs.

``mwparserfromhell`` is imported lazily, so the rest of the package remains
dependency-free; this module only needs it when actually extracting.
"""

import re
from typing import Any, Dict, List, Optional, Set

from .constants import HARV_TEMPLATES
from .parser import resolve_references


def extract_references(
    wikitext: str,
    inline_template_focus: Optional[set[str]] = None,
) -> List[Dict[str, Any]]:
    """Extract ref-like items from wikitext using mwparserfromhell parser.

    Parses and extracts all citation references from MediaWiki-formatted wikitext.
    Handles multiple reference types and maintains adjacency information for
    related templates (e.g., {{rp|page=X}} immediately following <ref> tags).

    Args:
        wikitext: Raw MediaWiki wikitext string potentially containing references.
        inline_template_focus: Optional set of template names (normalized) to attach
            as inline templates to preceding ref tags when they appear adjacent.
            If None, inline templates are not captured. Examples: {'citation needed',
            'dead link', 'full citation needed'}.

    Returns:
        List of dictionaries, one per reference found. Each dict contains:
            - ref_kind: Type of reference ('ref_tag', 'ref_tag+rp', 'r_template', 
              'sfn_template', 'sfnp_template')
            - ref_template_name: Template name if template-based, else None
            - ref_template_params: Dict of template parameters if template-based, else None
            - ref_rp_raw: Raw {{rp|...}} wikitext if attached to <ref>, else None
            - ref_rp_params: Dict of {{rp}} parameters if attached, else None
            - ref_raw: Complete raw wikitext of the reference (tag + any attached rp)
            - ref_contents: locator-bearing content (template string for bare templates)
            - ref_self_closing: Boolean, True if <ref .../> (self-closing)
            - ref_name: Value of 'name' attribute for refs; first positional param for r/sfn/sfnp
            - ref_group: Value of 'group' attribute if present, else None
            - ref_attrs: Dict of all attributes on <ref> tag (empty for templates)
            - ref_inline_templates: List of maintenance templates attached to this ref
                (empty if inline_template_focus was None)

    Note:
        - For <ref> tags, ref_template_name and ref_template_params are intentionally None
          because refs are tag-based, not template-based.
        - Dangling {{rp|...}} templates (not attached to a preceding ref) are discarded
        - For {{r|...}}, {{sfn|...}}, {{sfnp|...}}, ref_name stores the first positional
          parameter (the reference key) to enable reference resolution
    """
    import mwparserfromhell  # type: ignore
    from mwparserfromhell.nodes import Tag, Template, Text  # type: ignore

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

    pending_ref_index: Optional[int] = None
    pending_raw_parts: List[str] = []
    pending_can_attach_rp = False

    # Track a contiguous run of <ref> tags (separated only by whitespace) so that
    # inline maintenance templates immediately after can be associated to the
    # preceding one or small group of refs.
    inline_pending_ref_indices: List[int] = []

    focus = inline_template_focus

    def clear_pending() -> None:
        nonlocal pending_ref_index, pending_raw_parts, pending_can_attach_rp
        pending_ref_index = None
        pending_raw_parts = []
        pending_can_attach_rp = False

    def clear_inline_pending() -> None:
        nonlocal inline_pending_ref_indices
        inline_pending_ref_indices = []

    for node in getattr(wikicode, "nodes", []) or []:
        # If we're waiting to see whether {{rp}} immediately follows a <ref>,
        # accept only whitespace between them.
        if pending_can_attach_rp and isinstance(node, Text):
            text = str(node)
            if text.strip() == "":
                pending_raw_parts.append(text)
                continue
            clear_pending()

        # Inline-template adjacency: keep only whitespace between refs/templates.
        if inline_pending_ref_indices and isinstance(node, Text):
            if str(node).strip() == "":
                continue
            clear_inline_pending()

        if isinstance(node, Tag) and str(getattr(node, "tag", "")).lower() == "ref":
            attrs = tag_attrs(node)
            items.append(
                {
                    "ref_kind": "ref_tag",
                    "ref_template_name": None,
                    "ref_template_params": None,
                    "ref_rp_raw": None,
                    "ref_rp_params": None,
                    "ref_raw": str(node),
                    "ref_contents": str(getattr(node, "contents", "") or ""),
                    "ref_self_closing": bool(getattr(node, "self_closing", False)),
                    "ref_name": attrs.get("name"),
                    "ref_group": attrs.get("group"),
                    "ref_attrs": attrs,
                    "ref_inline_templates": [],
                }
            )
            pending_ref_index = len(items) - 1
            pending_raw_parts = [str(node)]
            pending_can_attach_rp = True

            # Start/extend contiguous ref run
            inline_pending_ref_indices.append(pending_ref_index)
            continue

        if isinstance(node, Template):
            name = str(getattr(node, "name", "")).strip()
            name_norm = _norm_template_name(name)
            if name_norm == "rp":
                rp_raw = str(node)
                rp_params = template_params(node)
                if pending_can_attach_rp and pending_ref_index is not None:
                    pending_raw_parts.append(rp_raw)
                    items[pending_ref_index]["ref_kind"] = "ref_tag+rp"
                    items[pending_ref_index]["ref_rp_raw"] = rp_raw
                    items[pending_ref_index]["ref_rp_params"] = rp_params
                    items[pending_ref_index]["ref_raw"] = "".join(pending_raw_parts)
                    clear_pending()
                # Skip dangling rp (not attached to a preceding ref tag)
                continue

            # Inline maintenance templates that follow a ref (or small group of refs).
            # Only attach when a focus set is provided (avoid attaching arbitrary templates).
            if inline_pending_ref_indices and focus and name_norm in focus:
                tpl_raw = str(node)
                tpl_params = template_params(node)
                for ridx in inline_pending_ref_indices:
                    if 0 <= ridx < len(items) and items[ridx].get("ref_kind") in {"ref_tag", "ref_tag+rp"}:
                        items[ridx].setdefault("ref_inline_templates", [])
                        items[ridx]["ref_inline_templates"].append(
                            {
                                "name": name_norm,
                                "raw": tpl_raw,
                                "params": tpl_params,
                            }
                        )
                # Keep inline_pending_ref_indices so multiple templates can attach.
                continue

            if name_norm == "r":
                r_raw = str(node)
                r_params = template_params(node)
                items.append(
                    {
                        "ref_kind": "r_template",
                        "ref_template_name": "r",
                        "ref_template_params": r_params,
                        "ref_rp_raw": None,
                        "ref_rp_params": None,
                        "ref_raw": r_raw,
                        "ref_contents": r_raw,
                        "ref_self_closing": False,
                        "ref_name": r_params.get('1'),  # First positional param is the ref key
                        "ref_group": None,
                        "ref_attrs": {},
                        "ref_inline_templates": [],
                    }
                )
                clear_pending()
                clear_inline_pending()
                continue

            if name_norm == "sfn":
                sfn_raw = str(node)
                sfn_params = template_params(node)
                items.append(
                    {
                        "ref_kind": "sfn_template",
                        "ref_template_name": "sfn",
                        "ref_template_params": sfn_params,
                        "ref_rp_raw": None,
                        "ref_rp_params": None,
                        "ref_raw": sfn_raw,
                        "ref_contents": sfn_raw,
                        "ref_self_closing": False,
                        "ref_name": sfn_params.get('1'),  # First positional param is the ref key
                        "ref_group": None,
                        "ref_attrs": {},
                        "ref_inline_templates": [],
                    }
                )
                clear_pending()
                clear_inline_pending()
                continue

            if name_norm == "sfnp":
                sfnp_raw = str(node)
                sfnp_params = template_params(node)
                items.append(
                    {
                        "ref_kind": "sfnp_template",
                        "ref_template_name": "sfnp",
                        "ref_template_params": sfnp_params,
                        "ref_rp_raw": None,
                        "ref_rp_params": None,
                        "ref_raw": sfnp_raw,
                        "ref_contents": sfnp_raw,
                        "ref_self_closing": False,
                        "ref_name": sfnp_params.get('1'),  # First positional param is the ref key
                        "ref_group": None,
                        "ref_attrs": {},
                        "ref_inline_templates": [],
                    }
                )
                clear_pending()
                clear_inline_pending()
                continue

            # Harvard author–date short-cite family — standalone inline short
            # footnotes (like sfn), carrying page locators. Parsed downstream via
            # the cite path into cite_type='harv'.
            if name_norm in HARV_TEMPLATES:
                harv_raw = str(node)
                harv_params = template_params(node)
                items.append(
                    {
                        "ref_kind": "harv_template",
                        "ref_template_name": name_norm,
                        "ref_template_params": harv_params,
                        "ref_rp_raw": None,
                        "ref_rp_params": None,
                        "ref_raw": harv_raw,
                        "ref_contents": harv_raw,
                        "ref_self_closing": False,
                        "ref_name": None,
                        "ref_group": None,
                        "ref_attrs": {},
                        "ref_inline_templates": [],
                    }
                )
                clear_pending()
                clear_inline_pending()
                continue

        # Any other node breaks the adjacency window.
        if pending_can_attach_rp:
            clear_pending()

        if inline_pending_ref_indices:
            clear_inline_pending()

    return items


def _norm_template_name(name: str) -> str:
    """Normalize a MediaWiki template name for comparison.

    Applies standard MediaWiki template name transformations:
    - Converts to lowercase
    - Replaces underscores with spaces
    - Collapses multiple spaces to single space
    - Strips "template:" namespace prefix if present

    Args:
        name: Template name as it appears in wikitext, possibly with namespace.

    Returns:
        Normalized template name suitable for set membership testing or comparison.

    Examples:
        >>> _norm_template_name("Template:Citation Needed")
        'citation needed'
        >>> _norm_template_name("Dead_Link")
        'dead link'
    """
    n = (name or "").strip().lower()
    n = n.replace("_", " ")
    n = re.sub(r"\s+", " ", n)
    if n.startswith("template:"):
        n = n.split(":", 1)[1].strip()
    return n




def parse_article(
    wikitext: str,
    language: str = 'en',
    inline_template_focus: Optional[Set[str]] = None,
) -> list:
    """Extract and resolve every reference in an article's wikitext.

    Convenience wrapper: :func:`extract_references` then
    :func:`resolve_references`. Requires ``mwparserfromhell`` (see the
    ``extract`` extra in pyproject.toml).
    """
    return resolve_references(
        extract_references(wikitext, inline_template_focus=inline_template_focus),
        language=language,
    )
