"""In-source locator parser for Wikipedia citations.

The public entry point is :func:`parse`, which takes the wikitext of a *single*
reference/citation (a ``<ref>...</ref>`` tag, a bare template such as
``{{cite book|...}}`` / ``{{sfn|...}}`` / ``{{rp|...}}``, or a plain-text
reference) and returns the in-source locators it declares, grouped as::

    {'cite_type': str | None, 'locators': {...}, 'ids': {...}, 'ref_key': str?}

Only stdlib is required. See :mod:`wikiloc.constants` for the locator vocabulary
and how to extend it to more templates, locators, identifiers or languages.
"""

import re
from typing import Dict, List, Optional

from .constants import LOC_PARAMS, ID_ALIASES, HARV_TEMPLATES

# Canonical identifier keys (isbn, doi, pmid, pmc, arxiv), kept in sync with the
# alias table so the public output can separate identifiers from locators.
_ID_KEYS = set(ID_ALIASES.values())

# Lowercased English template names known to LOC_PARAMS, used to resolve the
# longest matching name for 'cite ...' templates (e.g. 'cite video game'
# rather than the truncated 'cite video').
_EN_TEMPLATE_KEYS = {k.lower() for k in LOC_PARAMS['en']}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse(wikitext, language: str = 'en', with_flags: bool = False):
    """Parse reference wikitext and extract locators.

    Accepts either:
    - a single reference as a string — a ``<ref>...</ref>`` tag (optionally
      followed by an ``{{rp|...}}``), a bare template (``{{cite book|...}}``,
      ``{{citation|...}}``, ``{{r|...}}``, ``{{sfn|...}}``, ``{{sfnp|...}}``,
      ``{{harvnb|...}}``, ``{{rp|...}}``), or plain (untemplated) text; or
    - a list of references (strings or records) from one article, in which case
      they are resolved with name inheritance (see :func:`resolve_references`).

    Args:
        wikitext: A single reference string, or a list of reference strings/records.
        language: Language code ('en' or 'fr') for template and locator detection.
        with_flags: When True, run :func:`detect_locator_issues` and add its issue
            codes under a ``'flags'`` key (one key per reference for a list).
            Off by default so ``parse`` output stays a faithful transcription of
            the source; flagging is an opt-in audit step.

    Returns:
        For a single string, a dict with:
            - 'cite_type': normalized template name (e.g. 'cite book') or None
            - 'locators':  in-source locators found (page, pages, chapter, quote, ...)
            - 'ids':       identifiers found (isbn, doi, pmid, pmc, arxiv)
            - 'ref_key':   short-cite key for {{r}}/{{sfn}}/{{sfnp}} (only when present)
            - 'flags':     list of issue codes (only when ``with_flags=True``)
        For a list, the resolved flat dicts (one per reference, annotated with
        'ref_type' and 'ref_name', plus 'flags' when ``with_flags=True``), as
        returned by :func:`resolve_references`.

    Examples:
        >>> parse("{{cite book|title=X|isbn=978-0-13-468599-1|page=42}}")
        {'cite_type': 'cite book', 'locators': {'page': '42'}, 'ids': {'isbn': '978-0-13-468599-1'}}
        >>> parse("{{sfn|Smith|2020|p=42}}")
        {'cite_type': None, 'locators': {'p': '42'}, 'ids': {}, 'ref_key': 'Smith'}
        >>> parse("Smith, John (2020). Title. Publisher. p. 42")
        {'cite_type': None, 'locators': {'page': '42'}, 'ids': {}}
        >>> parse("{{cite book|title=X|pages=240}}", with_flags=True)['flags']
        ['pages_single']
    """
    if isinstance(wikitext, str):
        ref = _ref_from_wikitext(wikitext, language)
        flat = parse_reference(ref, language)
        result = _group_output(flat)
        if with_flags:
            result['flags'] = detect_locator_issues(result)
        return result
    # A list of references (strings or records): resolve with name inheritance.
    resolved = resolve_references(wikitext, language)
    if with_flags:
        for record in resolved:
            record['flags'] = detect_locator_issues(record)
    return resolved


def _ref_from_wikitext(wikitext: str, language: str = 'en') -> dict:
    """Classify a raw wikitext string into the minimal internal ``ref`` record.

    Mirrors, for a single reference, the structural detection that the batch
    extraction pipeline performs, so the string can be handed to
    :func:`parse_reference`.
    """
    s = (wikitext or "").strip()

    if s.lower().startswith('<ref'):
        attrs, inner, self_closing, rp_raw = _split_ref_tag(s)
        return {
            'ref_kind': 'ref_tag+rp' if rp_raw else 'ref_tag',
            'ref_contents': inner,
            'ref_rp_raw': rp_raw,
            'ref_name': _ref_name_from_attrs(attrs),
            'ref_self_closing': self_closing,
        }

    token = _leading_template_token(s)
    if token == 'r':
        return {'ref_kind': 'r_template', 'ref_contents': s}
    if token == 'sfn':
        return {'ref_kind': 'sfn_template', 'ref_contents': s}
    if token == 'sfnp':
        return {'ref_kind': 'sfnp_template', 'ref_contents': s}
    if token in HARV_TEMPLATES:
        return {'ref_kind': 'harv_template', 'ref_contents': s}
    if token == 'rp':
        # Standalone {{rp|...}}: reuse the ref_tag+rp path with empty contents.
        return {'ref_kind': 'ref_tag+rp', 'ref_contents': '', 'ref_rp_raw': s}

    # A bare cite/citation/other template, or free text: treat as ref contents.
    return {'ref_kind': 'ref_tag', 'ref_contents': s}


def _leading_template_token(s: str) -> Optional[str]:
    """Return the lowercased leading template name of ``{{name|...}}`` or None."""
    s = (s or "").strip()
    if not s.startswith('{{'):
        return None
    m = re.match(r'\s*([^|}]+)', s[2:])
    return m.group(1).strip().lower() if m else None


def _strip_leading_comments(text: str) -> str:
    """Drop leading whitespace and HTML comments from ``text``."""
    s = (text or "").lstrip()
    while s.startswith('<!--'):
        end = s.find('-->')
        if end == -1:
            break
        s = s[end + 3:].lstrip()
    return s


def _leading_balanced_template(text: str) -> Optional[str]:
    """Return the leading balanced ``{{...}}`` template, or None.

    Leading whitespace and HTML comments are skipped first, so
    ``<!-- note -->{{cite book|...}}`` is detected. Nested braces are counted,
    so ``{{cite book|quote=a {{b}} c}}`` is returned whole; an unbalanced
    leading ``{{`` yields None.
    """
    s = _strip_leading_comments(text)
    if not s.startswith('{{'):
        return None
    depth = 0
    i = 0
    n = len(s)
    while i < n:
        if s.startswith('{{', i):
            depth += 1
            i += 2
        elif s.startswith('}}', i):
            depth -= 1
            i += 2
            if depth == 0:
                return s[:i]
        else:
            i += 1
    return None


def _split_ref_tag(s: str):
    """Split a single ``<ref>`` string into (attrs, inner, self_closing, rp_raw).

    Any ``{{rp|...}}`` immediately following the closing tag is returned as
    ``rp_raw`` (mirroring the pipeline's adjacency attachment).
    """
    # Opening/closing form: <ref ...>INNER</ref> [ {{rp|...}} ]
    m = re.match(r'(?is)^<ref\b([^>]*)>(.*)</ref>\s*(.*)$', s)
    if m:
        attrs, inner, trailing = m.group(1), m.group(2), m.group(3).strip()
        rp = trailing if _leading_template_token(trailing) == 'rp' else None
        return attrs, inner, False, rp
    # Self-closing form: <ref ... /> [ {{rp|...}} ]
    m = re.match(r'(?is)^<ref\b([^>]*?)/>\s*(.*)$', s)
    if m:
        attrs, trailing = m.group(1), m.group(2).strip()
        rp = trailing if _leading_template_token(trailing) == 'rp' else None
        return attrs, '', True, rp
    return '', s, False, None


def _ref_name_from_attrs(attrs: str) -> Optional[str]:
    """Extract the ``name`` attribute value from a ``<ref>`` tag's attribute string."""
    if not attrs:
        return None
    m = re.search(r'name\s*=\s*"([^"]*)"|name\s*=\s*\'([^\']*)\'|name\s*=\s*(\S+)', attrs)
    if not m:
        return None
    return m.group(1) or m.group(2) or m.group(3)


def _group_output(flat: dict) -> dict:
    """Reshape the flat parse result into {cite_type, locators, ids, ref_key?}."""
    result = {'cite_type': flat.get('cite_type'), 'locators': {}, 'ids': {}}
    for key, value in flat.items():
        if key in ('cite_type', 'ref_key'):
            continue
        if key in _ID_KEYS:
            result['ids'][key] = value
        else:
            result['locators'][key] = value
    if 'ref_key' in flat:
        result['ref_key'] = flat['ref_key']
    return result


# ---------------------------------------------------------------------------
# Structured single-reference parsing (also used by the analysis pipeline)
# ---------------------------------------------------------------------------

def _ref_content(ref: dict) -> str:
    """Return a ref's locator-bearing content (template or plain text)."""
    return ref.get('ref_contents') or ''


def parse_reference(ref: dict, language: str = 'en'):
    """Parse a reference record and extract location information.

    Handles different reference kinds and extracts location info (page, pages,
    chapter, etc.) from the appropriate fields. Returns a flattened dictionary
    with cite_type and any location indicators found.

    Args:
        ref: A reference record with the keys ref_kind, ref_contents,
             ref_rp_raw, ref_name and ref_self_closing (see extract_references).
        language: Language code ('en' or 'fr') for template and location keyword detection

    Returns:
        Flattened dictionary with:
            - cite_type: The type of citation (e.g., 'cite web', 'cite book')
            - <location_key>: Location indicators (page, pages, chapter, etc.)

    Examples:
        ref_tag with {{cite web}}:
            returns {'cite_type': 'cite web', 'page': '42', ...}

        ref_tag+rp with {{rp|page=42}}:
            returns {'cite_type': 'cite book', 'page': '42', ...}

        r_template {{r|Smith2020|page=42}}:
            returns {'cite_type': None, 'ref_key': 'Smith2020', 'page': '42'}

        sfn_template {{sfn|Author|Year|p=42}}:
            returns {'cite_type': None, 'ref_key': 'Author', 'page': '42'}
    """
    if ref['ref_kind'] == 'ref_tag':
        return _parse_ref_tag_contents(ref['ref_contents'], language)

    elif ref['ref_kind'] == 'ref_tag+rp':
        # Parse main cite template first
        main_ref_dict = _parse_ref_tag_contents(ref['ref_contents'], language)
        # Parse {{rp|...}} template
        rp_dict = _parse_rp_template(ref['ref_rp_raw'], language)
        # Merge with rp_dict taking priority for location info (it's more specific)
        # Keep cite_type from main ref, but override location fields with rp
        cite_type = main_ref_dict.pop('cite_type', None)
        main_ref_dict.update(rp_dict)
        main_ref_dict['cite_type'] = cite_type  # Restore original cite_type
        return main_ref_dict

    elif ref['ref_kind'] == 'r_template':
        return _parse_r_template(_ref_content(ref), language)

    elif ref['ref_kind'] == 'sfn_template':
        return _parse_sfn_template(_ref_content(ref), language)

    elif ref['ref_kind'] == 'sfnp_template':
        return _parse_sfnp_template(_ref_content(ref), language)

    elif ref['ref_kind'] == 'harv_template':
        # Standalone Harvard short-cite; parsed via the cite path -> cite_type='harv'.
        return _parse_cite_template(_ref_content(ref), language)

    else:
        # Unknown reference kind
        return {'cite_type': None}


def _merge_untemplated_fallback(parsed: dict, fallback: dict) -> dict:
    """Merge a locator-less template parse with plain-text locators."""
    merged = dict(fallback)
    if parsed.get('cite_type') and not merged.get('cite_type'):
        merged['cite_type'] = parsed['cite_type']
    for key, value in parsed.items():
        merged.setdefault(key, value)
    return merged


def _parse_ref_tag_contents(content: str, language: str = 'en'):
    """Parse ``<ref>`` contents, tolerating text around a leading template.

    A leading balanced template is parsed as the citation; trailing text after
    it (punctuation, prose, a maintenance comment) no longer defeats detection
    (WL-1). If the template declares no locator, plain-text page markers in the
    full contents are used as a fallback, so ``{{cite web|...}} See p. 5.``
    still finds ``p. 5``. Short-cite templates wrapped in a ``<ref>``
    (``{{sfn}}``/``{{sfnp}}``/``{{r}}``) are routed to their own parsers
    (WL-3). Content with no leading template is parsed as untemplated text.
    """
    lead = _leading_balanced_template(content)
    if lead is None:
        return _parse_untemplated_ref(content, language)

    token = _leading_template_token(lead)
    if token == 'sfn':
        parsed = _parse_sfn_template(lead, language)
    elif token == 'sfnp':
        parsed = _parse_sfnp_template(lead, language)
    elif token == 'r':
        parsed = _parse_r_template(lead, language)
    elif token == 'rp':
        parsed = _parse_rp_template(lead, language)
    else:
        parsed = _parse_cite_template(lead, language)

    if not _has_no_locators(parsed):
        return parsed
    if content.strip() == lead:
        return parsed
    # The template declares no locator: keep it for cite_type/ids, but also
    # pick up plain-text page markers in the rest of the contents.
    return _merge_untemplated_fallback(parsed, _parse_untemplated_ref(content, language))


def resolve_references(refs: list, language: str = 'en') -> list:
    """Resolve a list of references from one article, applying name inheritance.

    Each reference is a plain dict with (minimally): ``ref_kind``,
    ``ref_contents`` (the locator-bearing content), ``ref_rp_raw``,
    ``ref_name`` and ``ref_self_closing``. Extra fields are ignored.

    A repeated use (self-closing named ref) inherits its main definition's
    locators and ``cite_type``; the use's own parameters take precedence (the
    main's fields are only copied when not already present). ``ref_key`` from
    ``{{r}}``/``{{sfn}}``/``{{sfnp}}`` is merged into ``ref_name`` so short-cites
    resolve against same-named main definitions.

    Returns one resolved flat dict per input ref, each annotated with
    ``ref_type`` and ``ref_name``.
    """
    # Normalise input: accept either reference records or raw wikitext strings.
    refs = [_ref_from_wikitext(ref, language) if isinstance(ref, str) else ref for ref in refs]
    parsed = [parse_reference(ref, language) for ref in refs]

    mains = {}
    for i, ref in enumerate(refs):
        if _determine_ref_type(ref) == 'main' and ref.get('ref_name'):
            mains[ref['ref_name']] = parsed[i]

    resolved = []
    for ref, own in zip(refs, parsed):
        ref_type = _determine_ref_type(ref)
        name = ref.get('ref_name')
        ref_key = own.get('ref_key')
        if ref_key and not name:
            name = ref_key
        out = dict(own)
        out['ref_type'] = ref_type
        out['ref_name'] = name
        if ref_type in ('repeated', 'repeated_rp', 'r', 'rp', 'sfn', 'sfnp') and name in mains:
            parent = mains[name]
            if parent.get('cite_type'):
                out['cite_type'] = parent['cite_type']
            for key, value in parent.items():
                if key != 'cite_type' and key not in out:
                    out[key] = value
        resolved.append(out)
    return resolved


def _detect_template_name(wikitext: str, language: str = 'en') -> Optional[str]:
    """Detect the template name in wikitext, handling language-specific patterns.

    For English: Looks for 'cite ...' pattern (e.g., {{cite web}})
    For French: Looks for any template name defined in LOC_PARAMS
    For other languages: Falls back to 'cite' pattern

    Args:
        wikitext: The template wikitext to parse
        language: Language code ('en' or 'fr')

    Returns:
        The normalized template name (lowercase) or None if not detected

    Examples:
        >>> _detect_template_name("{{cite web | url=... }}", 'en')
        'cite web'

        >>> _detect_template_name("{{Ouvrage | title=... }}", 'fr')
        'ouvrage'

        >>> _detect_template_name("{{Lien web | url=... }}", 'fr')
        'lien web'
    """
    wikitext = wikitext.strip()
    if not wikitext.startswith('{{') or not wikitext.endswith('}}'):
        return None

    # Extract template name (between {{ and first | or }})
    content = wikitext[2:-2]
    match = re.match(r'\s*(\w+(?:\s+\w+)*)', content)
    if not match:
        return None

    template_name = match.group(1).strip()

    if language == 'en':
        first = template_name.split()[0].lower() if template_name.split() else ''
        # CS2 generic citation template.
        if first == 'citation':
            return 'citation'
        # Harvard author–date short-cite family — collapse all variants to 'harv'.
        if first in HARV_TEMPLATES:
            return 'harv'
        # For English, normalize 'cite ...' templates. Prefer a known
        # three-word name ('cite video game', 'cite av media'); otherwise keep
        # the two-word prefix as before (unknown templates retain their name
        # and fall back to the generic 'cite' locator list in
        # _parse_cite_template).
        if template_name.lower().startswith('cite'):
            parts = template_name.split()
            if len(parts) >= 3:
                candidate = " ".join(parts[:3]).lower()
                if candidate in _EN_TEMPLATE_KEYS:
                    return candidate
            if len(parts) >= 2:
                return f"{parts[0].lower()} {parts[1].lower()}"
            return template_name.lower()
        return None

    elif language == 'fr':
        # For French, check if template name is in LOC_PARAMS
        fr_templates = LOC_PARAMS.get('fr', {})
        template_norm = template_name.lower()

        # First try exact match (handles single-word templates)
        if template_norm in fr_templates:
            return template_norm

        # Then try case-insensitive match against fr_templates keys
        for key in fr_templates.keys():
            if key.lower() == template_norm:
                return key.lower()

        # Unknown / unlisted French template: return its name so
        # _parse_cite_template can apply the generic 'cite' locator fallback
        # (parity with unknown English {{cite *}} templates) instead of
        # silently dropping every locator.
        return template_norm

    else:
        # Default to English pattern for unknown languages
        return _detect_template_name(wikitext, 'en')


def _parse_cite_template(wikitext: str, language: str = 'en'):
    """Parse a cite/citation template to extract location info.

    Handles both English-style templates ({{cite web}}, etc.) and French-style
    templates ({{Ouvrage}}, {{Lien web}}, etc.). Detects template type and
    extracts parameters matching location indicators for the language.

    Args:
        wikitext: The template wikitext (e.g., "{{cite web | url=... | page=42}}")
        language: Language code ('en' or 'fr') to determine location keywords

    Returns:
        Dictionary with keys:
            - 'cite_type': The cite template type (e.g., 'cite web') or None
            - <location_key>: Any location indicator found (page, pages, chapter, etc.)

    Examples:
        >>> _parse_cite_template("{{cite web | url=http://example.com | page=42}}", 'en')
        {'cite_type': 'cite web', 'page': '42'}

        >>> _parse_cite_template("{{Ouvrage | titre=Example | page=100}}", 'fr')
        {'cite_type': 'ouvrage', 'page': '100'}
    """
    out = {'cite_type': None}

    # Detect template name (language-aware)
    template_name = _detect_template_name(wikitext, language)
    if not template_name:
        return out

    # Get location indicators for this template
    lang_params = LOC_PARAMS.get(language, LOC_PARAMS['en'])

    # Find location keywords with case-insensitive lookup
    location_keywords = []
    for key in lang_params.keys():
        if key.lower() == template_name.lower():
            location_keywords = lang_params.get(key, [])
            break

    # No template-specific list: fall back to the language's generic 'cite'
    # locators. English keeps its historical 'cite ...' prefix gate; other
    # languages (e.g. French) have no naming convention, so any unrecognised
    # template gets the generic list rather than no locators at all (WL-5).
    if not location_keywords and (language != 'en' or template_name.lower().startswith('cite')):
        for key in lang_params.keys():
            if key.lower() == 'cite':
                location_keywords = lang_params.get(key, [])
                break

    # Store cite_type (normalized template name)
    out['cite_type'] = template_name

    # Extract all template parameters
    params = _extract_template_params(wikitext)

    # Filter and add location indicators to output (flattened structure)
    for key, value in params.items():
        if key.lower() in location_keywords:
            out[key.lower()] = value

    # Extract identifiers, normalising aliases to canonical keys
    for key, value in params.items():
        canonical = ID_ALIASES.get(key.lower())
        if canonical and canonical not in out:
            out[canonical] = value.strip()

    return out


# A page token is either an optional single letter + one or more digits ("42",
# "S5", "A01", "11076", "1000000") or a strict Roman numeral ("iv", "xiv",
# "MCMXCIV"). There is no digit cap: absurd magnitudes are caught by the
# 'page_huge' flag rather than rejected as unparseable.
#
# The Roman grammar rejects malformed values ("IIII", "VX") while accepting the
# classical 1..4999 forms, case-insensitively. The leading lookahead keeps the
# otherwise all-optional pattern from matching the empty string.
_ROMAN_PATTERN = (
    r'(?=[MDCLXVI])'
    r'M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})'
)
_ROMAN = re.compile(_ROMAN_PATTERN, re.IGNORECASE)
_PAGE_TOKEN_PATTERN = r'(?:[A-Za-z]?\d+|' + _ROMAN_PATTERN + r')'
_PAGE_TOKEN = re.compile(_PAGE_TOKEN_PATTERN, re.IGNORECASE)
# A page range: two page tokens separated by one or more dashes (ASCII or the
# Unicode en/em/minus dashes). Each end may be numeric or a Roman numeral.
_PAGE_RANGE = re.compile(
    r'(' + _PAGE_TOKEN_PATTERN + r')\s*[–—−-]+\s*(' + _PAGE_TOKEN_PATTERN + r')',
    re.IGNORECASE,
)

_ROMAN_VALUES = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}

# Flag thresholds (tunable). A page/p number above PAGE_HUGE_THRESHOLD, or a
# pages/pp range longer than PAGES_RANGE_HUGE_THRESHOLD, is almost certainly a
# data error (a total-page count, a typo, or a non-locator value).
PAGE_HUGE_THRESHOLD = 99999
PAGES_RANGE_HUGE_THRESHOLD = 999


def _roman_to_int(token: str) -> int:
    """Convert a validated Roman numeral to int (``"xiv"`` → 14)."""
    total = 0
    prev = 0
    for ch in reversed(token.upper()):
        value = _ROMAN_VALUES[ch]
        if value < prev:
            total -= value
        else:
            total += value
            prev = value
    return total


def _page_token_to_int(token: str) -> Optional[int]:
    """Convert one page token to int, whether digits or Roman, else None."""
    token = (token or '').strip()
    if not token:
        return None
    if _ROMAN.fullmatch(token):
        return _roman_to_int(token)
    digits = re.sub(r'\D', '', token)
    return int(digits) if digits else None


def _range_bounds(value: str):
    """Return (lo, hi) for the first page range found in ``value``, else None.

    Expands abbreviated numeric ends ("446–52" → (446, 452), "142–3" →
    (142, 143)) and understands Roman-numeral ranges ("iv–viii" → (4, 8)).
    Mirrors the range detection used by :func:`_parse_page_range`.
    """
    m = _PAGE_RANGE.search(value or '')
    if not m:
        return None
    lo_tok, hi_tok = m.group(1), m.group(2)
    lo, hi = _page_token_to_int(lo_tok), _page_token_to_int(hi_tok)
    if lo is None or hi is None:
        return None
    # Abbreviated numeric ends only: "446–52" → 452, "142–3" → 143. Roman
    # endpoints have no abbreviation convention.
    lo_digits, hi_digits = re.sub(r'\D', '', lo_tok), re.sub(r'\D', '', hi_tok)
    if lo_digits and hi_digits and len(hi_digits) < len(lo_digits):
        hi = int(lo_digits[:len(lo_digits) - len(hi_digits)] + hi_digits)
    return lo, hi


def _page_count_of_item(item: str) -> Optional[int]:
    """Page count for one page token or range, else None.

    ``"42"`` → 1, ``"S5"`` → 1, ``"56–57"`` → 2, ``"446–52"`` → 7, ``"foo"`` → None.
    """
    item = (item or '').strip()
    if not item:
        return None
    if _PAGE_TOKEN.fullmatch(item):
        return 1
    bounds = _range_bounds(item)
    if bounds is not None:
        lo, hi = bounds
        return hi - lo + 1 if hi >= lo else 1
    return None


def _parse_page_range(value: str) -> Optional[int]:
    """Parse a page or page-range string into a page count.

    Handles: "42" → 1, "100-150" → 51, "100, 105, 110" → 3,
    "S1-S5" → 5, abbreviated ends ("446–52" → 7), and mixed comma lists
    of single pages and ranges ("21, 31, 56–57" → 4). Returns None if any
    comma-separated item is unparseable.
    """
    if not value:
        return None
    v = value.strip()

    # Comma-separated list of single pages and/or ranges.
    if ',' in v:
        parts = [p.strip() for p in v.split(',') if p.strip()]
        if not parts:
            return None
        total = 0
        for part in parts:
            count = _page_count_of_item(part)
            if count is None:
                return None
            total += count
        return total

    return _page_count_of_item(v)


def _locators_of(parsed_ref: dict) -> dict:
    """Return the flat locator map from a parse result or a flat record.

    Accepts either the grouped dict returned by :func:`parse`
    (``{'locators': {...}}``) or a flat dict whose locator keys sit at the top
    level (as returned by :func:`resolve_references`).
    """
    if isinstance(parsed_ref, dict) and 'locators' in parsed_ref:
        return parsed_ref['locators'] or {}
    return parsed_ref or {}


def compute_located_pages(parsed_ref: dict) -> Optional[int]:
    """Compute the located page count from page-related locators only.

    Accepts either a grouped parse result or a flat locator record. Uses page/p
    (a single page counts as 1) and pages/pp (a page range counts as its
    length); quote/chapter/at and other non-paginated locators are deliberately
    excluded. When several page locators coexist, returns the minimum.
    """
    locs = _locators_of(parsed_ref)
    estimates = []

    page_val = locs.get('page') or locs.get('p')
    if page_val:
        parsed = _parse_page_range(page_val)
        estimates.append(parsed if parsed else 1)

    pages_val = locs.get('pages') or locs.get('pp')
    if pages_val:
        parsed = _parse_page_range(pages_val)
        if parsed:
            estimates.append(parsed)

    return min(estimates) if estimates else None


def _classify_page_value(value: str) -> Optional[str]:
    """Classify a page/page-range string, mirroring ``_parse_page_range``.

    Returns 'single', 'range', 'list' or 'unparseable' (None when empty).
    """
    v = (value or '').strip()
    if not v:
        return None
    if ',' in v:
        parts = [p.strip() for p in v.split(',') if p.strip()]
        if not parts:
            return 'unparseable'
        return 'list' if all(_page_count_of_item(p) is not None for p in parts) else 'unparseable'
    if _PAGE_RANGE.search(v):
        return 'range'
    if _PAGE_TOKEN.fullmatch(v):
        return 'single'
    return 'unparseable'


def _numbers_in(value: str) -> list:
    """Return every integer appearing in ``value`` (empty list when none)."""
    return [int(n) for n in re.findall(r'\d+', value or '')]


def _is_reversed_range(value: str) -> bool:
    """True when a page range runs backwards (e.g. "150-100", "S5-S1")."""
    bounds = _range_bounds((value or '').strip())
    return bounds is not None and bounds[1] < bounds[0]


def _is_clean_page_value(value: str) -> bool:
    """True when a page value holds only page tokens, separators and whitespace.

    "100-150", "42", "S1-S5", "100, 105" are clean; "200–201 & sketch 19" is
    not (a range can be extracted from it, but it also carries prose).
    """
    cleaned = _PAGE_TOKEN.sub('', value or '')
    cleaned = re.sub(r'[–—−\-,\s]', '', cleaned)
    return cleaned == ''


def _page_span(value: str):
    """Return the (lo, hi) numeric span of a page value, or None if unparseable."""
    v = (value or '').strip()
    if ',' in v:
        spans = [_page_span(p) for p in v.split(',') if p.strip()]
        spans = [s for s in spans if s is not None]
        if not spans:
            return None
        return (min(s[0] for s in spans), max(s[1] for s in spans))
    bounds = _range_bounds(v)
    if bounds is not None:
        return (min(bounds), max(bounds))
    nums = _numbers_in(v)
    return (min(nums), max(nums)) if nums else None


def _page_pages_conflict(page_val: str, pages_val: str) -> bool:
    """True when a page/p pinpoint falls outside the pages/pp range.

    The pages value must itself be a range or list; a single ``pages`` number
    is more likely a total-page count and is covered by 'pages_single'.
    """
    if _classify_page_value(pages_val) not in ('range', 'list'):
        return False
    page_span = _page_span(page_val)
    pages_span = _page_span(pages_val)
    if page_span is None or pages_span is None:
        return False
    return page_span[0] < pages_span[0] or page_span[1] > pages_span[1]


# Keys that are not locators in a flat record: cite/ref metadata and identifiers.
_NON_LOCATOR_KEYS = {'cite_type', 'ref_type', 'ref_name', 'ref_key', 'flags'} | _ID_KEYS


def _has_no_locators(parsed_ref: dict) -> bool:
    """True when a parse result carries no locator at all.

    For a grouped result the ``locators`` map is authoritative; for a flat
    record, cite/ref metadata and identifiers are ignored, so that e.g.
    ``{'cite_type': 'cite book', 'isbn': ...}`` counts as locator-less.
    """
    if isinstance(parsed_ref, dict) and 'locators' in parsed_ref:
        return not parsed_ref.get('locators')
    return not any(
        key not in _NON_LOCATOR_KEYS and value
        for key, value in (parsed_ref or {}).items()
    )


def detect_locator_issues(parsed_ref: dict) -> list:
    """Detect suspicious or missing locator values, for later manual review.

    Accepts either a grouped parse result or a flat locator record. Returns a
    list of issue codes (empty when nothing looks off):
      - 'no_locator'           the reference declares no locator at all.
      - 'pages_single'         a pages/pp value is a single page number
                               (often a total-page count, not a locator).
      - 'page_range'           a page/p value holds a range or comma list
                               (probably belongs in pages).
      - 'page_unparseable'     a page/p value could not be parsed.
      - 'pages_unparseable'    a pages/pp value could not be parsed.
      - 'page_huge'            a page/p number exceeds ``PAGE_HUGE_THRESHOLD``.
      - 'pages_range_huge'     a pages/pp range exceeds
                               ``PAGES_RANGE_HUGE_THRESHOLD``.
      - 'page_reversed_range'  a page/p range runs backwards (hi < lo).
      - 'pages_reversed_range' a pages/pp range runs backwards (hi < lo).
      - 'page_noisy'           a parseable page/p value carries extra prose.
      - 'page_pages_conflict'  page/p falls outside the pages/pp range.

    'no_locator' is returned alone; the remaining codes may co-occur. Order is
    stable and de-duplicated.
    """
    locs = _locators_of(parsed_ref)
    if _has_no_locators(parsed_ref):
        return ['no_locator']

    flags = []
    for key in ('page', 'p'):
        v = locs.get(key)
        if not v:
            continue
        kind = _classify_page_value(v)
        if kind in ('range', 'list'):
            flags.append('page_range')
        elif kind == 'unparseable':
            flags.append('page_unparseable')
        # Magnitude is independent of grammar: flag an oversized number even
        # when the value is otherwise unparseable.
        span = _page_span(v)
        if span and span[1] > PAGE_HUGE_THRESHOLD:
            flags.append('page_huge')
        if kind != 'unparseable':
            if _is_reversed_range(v):
                flags.append('page_reversed_range')
            if not _is_clean_page_value(v):
                flags.append('page_noisy')

    for key in ('pages', 'pp'):
        v = locs.get(key)
        if not v:
            continue
        kind = _classify_page_value(v)
        if kind == 'single':
            flags.append('pages_single')
        elif kind == 'unparseable':
            flags.append('pages_unparseable')
        if kind != 'unparseable':
            if _is_reversed_range(v):
                flags.append('pages_reversed_range')
            count = _parse_page_range(v)
            if count and count > PAGES_RANGE_HUGE_THRESHOLD:
                flags.append('pages_range_huge')

    page_val = locs.get('page') or locs.get('p')
    pages_val = locs.get('pages') or locs.get('pp')
    if page_val and pages_val and _page_pages_conflict(page_val, pages_val):
        flags.append('page_pages_conflict')

    return list(dict.fromkeys(flags))


def _extract_template_params(wikitext: str) -> Dict[str, str]:
    """Extract key=value parameters from a {{template|key=value|...}} template.

    Handles nested braces correctly by tracking brace depth when splitting on pipes.

    Args:
        wikitext: Template wikitext to parse

    Returns:
        Dictionary mapping parameter names to values

    Examples:
        >>> _extract_template_params("{{cite web|title=Example|page=42}}")
        {'title': 'Example', 'page': '42'}

        >>> _extract_template_params("{{cite book|author=Smith|quote=A {{nested}} template}}")
        {'author': 'Smith', 'quote': 'A {{nested}} template'}
    """
    params = {}

    # Extract template content (between outer {{ and }})
    # Find first {{ and last }}
    wikitext = wikitext.strip()
    if not wikitext.startswith('{{') or not wikitext.endswith('}}'):
        return params

    # Remove the outer braces
    content = wikitext[2:-2]

    # Split by pipe while respecting nested braces
    parts = []
    current = []
    brace_depth = 0
    bracket_depth = 0

    for char in content:
        if char == '{':
            brace_depth += 1
        elif char == '}':
            brace_depth -= 1
        elif char == '[':
            bracket_depth += 1
        elif char == ']':
            bracket_depth -= 1
        elif char == '|' and brace_depth == 0 and bracket_depth == 0:
            # Found a parameter separator
            parts.append(''.join(current).strip())
            current = []
            continue

        current.append(char)

    if current:
        parts.append(''.join(current).strip())

    # Parse each part as either key=value or positional parameter
    for i, part in enumerate(parts):
        if not part:
            continue

        if '=' in part:
            # Key=value parameter
            key, value = part.split('=', 1)
            key = key.strip()
            value = value.strip()
            params[key] = value
        else:
            # Positional parameter (usually just the template name in position 0)
            if i > 0:  # Skip the template name
                params[str(i)] = part

    return params

def _extract_ids_from_text(text: str) -> Dict[str, str]:
    """Extract identifiers from free-form text (no cite template).

    Handles {{ISBN|...}}, plain 'ISBN 978-...', {{doi|...}}, 'doi:10.xxx',
    {{PMID|...}}, 'PMID 12345', {{arxiv|...}}, 'arxiv:2011.10121'.
    """
    if not text:
        return {}
    ids: Dict[str, str] = {}

    # ISBN: {{ISBN|...}} or plain text
    m = re.search(r'\{\{ISBN\|([^}]+)\}\}', text, re.IGNORECASE)
    if m:
        ids['isbn'] = m.group(1).strip()
    else:
        m = re.search(r'\bISBN[\s:=]+([0-9][0-9\-– Xx]{7,17})', text, re.IGNORECASE)
        if m:
            ids['isbn'] = m.group(1).strip().rstrip('-– ')

    # DOI: {{doi|...}} or doi:10.xxx / doi=10.xxx
    m = re.search(r'\{\{doi\|([^}]+)\}\}', text, re.IGNORECASE)
    if m:
        ids['doi'] = m.group(1).strip()
    else:
        m = re.search(r'\bdoi[\s:=]+(10\.\S+)', text, re.IGNORECASE)
        if m:
            ids['doi'] = m.group(1).strip().rstrip('.,;)]')

    # PMID: {{PMID|...}} or PMID 12345
    m = re.search(r'\{\{PMID\|(\d+)\}\}', text, re.IGNORECASE)
    if m:
        ids['pmid'] = m.group(1)
    else:
        m = re.search(r'\bPMID[\s:=]+(\d+)', text, re.IGNORECASE)
        if m:
            ids['pmid'] = m.group(1)

    # arXiv: {{arxiv|...}} or arxiv:NNNN.NNNNN
    m = re.search(r'\{\{arxiv\|([^}]+)\}\}', text, re.IGNORECASE)
    if m:
        ids['arxiv'] = m.group(1).strip()
    else:
        m = re.search(r'\barxiv[\s:=]+(\S+)', text, re.IGNORECASE)
        if m:
            ids['arxiv'] = m.group(1).strip().rstrip('.,;)]')

    # PMC: {{PMC|...}} or PMC 12345
    m = re.search(r'\{\{PMC\|(\d+)\}\}', text, re.IGNORECASE)
    if m:
        ids['pmc'] = m.group(1)
    else:
        m = re.search(r'\bPMC[\s:=]+(\d+)', text, re.IGNORECASE)
        if m:
            ids['pmc'] = m.group(1)

    return ids


def _parse_untemplated_ref(wikitext: str, language: str = 'en'):
    """Parse untemplated reference content to extract location info.

    For references without {{cite ...}} templates, use pattern matching to detect
    common locator phrases like "p. 42", "pp. 100-150", etc.

    Args:
        wikitext: Reference content as plain text
        language: Language code (for consistency with other parsers)

    Returns:
        Dictionary with cite_type=None and any extracted page/pages info

    Examples:
        >>> _parse_untemplated_ref("Smith, John (2020). Title. Publisher. p. 42")
        {'cite_type': None, 'page': '42'}

        >>> _parse_untemplated_ref("Smith et al. (2019). pp. 100-150")
        {'cite_type': None, 'pages': '100-150'}
    """
    out = {'cite_type': None}

    # Extract identifiers from free text ({{ISBN|...}}, doi:..., etc.)
    out.update(_extract_ids_from_text(wikitext))

    # Strip identifiers and URLs before the page-number regex, so ISBN digits
    # ("978-950"), DOIs, and URL fragments ("pg=RA5-PA9", "/page/143", dates in
    # query strings) cannot be mistaken for page numbers.
    t = wikitext or ""
    t = re.sub(r'\{\{ISBN\|[^}]+\}\}', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\bISBN[\s:=]+[0-9][0-9\-– Xx]{7,17}', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\{\{doi\|[^}]+\}\}', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\bdoi[\s:=]+10\.\S+', '', t, flags=re.IGNORECASE)
    t = re.sub(r'https?://\S+', ' ', t)
    t = re.sub(r"\s+", " ", t).strip()
    t_l = t.lower()

    # A page token: optional single section letter + up to 6 digits. Free text
    # keeps this cap (unlike template page/pages values, which are uncapped) to
    # avoid matching long IDs; a longer digit run is simply not detected here.
    tok = r"[a-z]?\d{1,6}"      # up to 6 digits: single pages like Keesing's 11076
    range_pat = rf"{tok}\s*[-–—]\s*{tok}"

    def _is_year_range(s: str) -> bool:
        nums = re.findall(r"\d+", s)
        return len(nums) >= 2 and all(1000 <= int(n) <= 2099 for n in nums[:2])

    # Require an explicit page marker (p./pp./page/pages); we no longer accept a
    # bare numeric range, which matched year ranges, scorelines and dates.
    # 1) pp./pages + range -> pages
    m = re.search(rf"\b(pp\.?|pages?|pgs\.?)\s*({range_pat})\b", t_l)
    if m and not _is_year_range(m.group(2)):
        out['pages'] = m.group(2).strip()
        return out

    # 2) p./page + range or single page
    m = re.search(rf"\b(pg\.?|p\.?|page)\s*({range_pat}|{tok})\b", t_l)
    if m and not _is_year_range(m.group(2)):
        val = m.group(2).strip()
        out['pages' if re.search(r'[-–—]', val) else 'page'] = val
        return out

    return out


def _parse_rp_template(wikitext: str, language: str = 'en'):
    """Parse an {{rp|...}} template to extract location info.

    The {{rp|...}} (reference pointer) template is used to specify a location
    (page, section, etc.) in a reference. Can contain positional or named params.

    Args:
        wikitext: The {{rp|...}} template wikitext
        language: Language code for keyword matching

    Returns:
        Dictionary with any location information extracted from the template

    Examples:
        >>> _parse_rp_template("{{rp|page=42}}")
        {'cite_type': None, 'page': '42'}

        >>> _parse_rp_template("{{rp|59–60}}")
        {'cite_type': None, 'pages': '59–60'}
    """
    out = {'cite_type': None}

    # Get location indicators for rp templates
    location_keywords = LOC_PARAMS.get(language, LOC_PARAMS['en']).get('rp', [])

    # Extract parameters
    params = _extract_template_params(wikitext)

    # {{rp}} can have positional params that need interpretation
    # First check for named parameters
    for key, value in params.items():
        if key.lower() in location_keywords:
            out[key.lower()] = value

    # Positional parameters in {{rp}} typically represent pages/page ranges
    # {{rp|42}} means page 42, {{rp|59–60}} means pages 59-60
    if '1' in params and 'page' not in out and 'pages' not in out:
        positional_value = params['1']
        # Heuristic: if it contains a range character (–, -, en dash), it's pages
        if any(char in positional_value for char in ['–', '-', '‐', '−']):
            out['pages'] = positional_value
        else:
            out['page'] = positional_value

    return out


def _parse_r_template(wikitext: str, language: str = 'en'):
    """Parse an {{r|...}} template to extract location info.

    The {{r|...}} template is a shorthand citation that references a bibliographic
    key. It can optionally include page or location information.

    Args:
        wikitext: The {{r|...}} template wikitext
        language: Language code for keyword matching

    Returns:
        Dictionary with the citation key and any location information

    Examples:
        >>> _parse_r_template("{{r|Smith2020}}")
        {'cite_type': None, 'ref_key': 'Smith2020'}

        >>> _parse_r_template("{{r|Smith2020|page=42}}")
        {'cite_type': None, 'ref_key': 'Smith2020', 'page': '42'}
    """
    out = {'cite_type': None}

    # Get location indicators for r templates
    location_keywords = LOC_PARAMS.get(language, LOC_PARAMS['en']).get('r', [])

    # Extract parameters
    params = _extract_template_params(wikitext)

    # First positional parameter is the reference key
    if '1' in params:
        out['ref_key'] = params['1']

    # Extract any location indicators
    for key, value in params.items():
        if key.lower() in location_keywords:
            out[key.lower()] = value

    return out


def _parse_sfn_template(wikitext: str, language: str = 'en'):
    """Parse an {{sfn|...}} (shortened footnote) template to extract location info.

    The {{sfn|...}} template is a shorthand citation similar to {{r|...}}.
    Format is typically: {{sfn|Author|Year|...location params...}}

    Args:
        wikitext: The {{sfn|...}} template wikitext
        language: Language code for keyword matching

    Returns:
        Dictionary with the citation key and any location information

    Examples:
        >>> _parse_sfn_template("{{sfn|Smith|2020}}")
        {'cite_type': None, 'ref_key': 'Smith'}

        >>> _parse_sfn_template("{{sfn|Smith|2020|p=42}}")
        {'cite_type': None, 'ref_key': 'Smith', 'page': '42'}
    """
    out = {'cite_type': None}

    # Get location indicators for sfn templates
    location_keywords = LOC_PARAMS.get(language, LOC_PARAMS['en']).get('sfn', [])

    # Extract parameters
    params = _extract_template_params(wikitext)

    # First positional parameter is the reference key (author)
    if '1' in params:
        out['ref_key'] = params['1']

    # Extract any location indicators
    for key, value in params.items():
        if key.lower() in location_keywords:
            out[key.lower()] = value

    return out


def _parse_sfnp_template(wikitext: str, language: str = 'en'):
    """Parse an {{sfnp|...}} (shortened footnote page) template to extract location info.

    The {{sfnp|...}} template is similar to {{sfn|...}} but expects page parameters.
    Format is typically: {{sfnp|Author|Year|page=X}}

    Args:
        wikitext: The {{sfnp|...}} template wikitext
        language: Language code for keyword matching

    Returns:
        Dictionary with the citation key and any location information

    Examples:
        >>> _parse_sfnp_template("{{sfnp|Smith|2020}}")
        {'cite_type': None, 'ref_key': 'Smith'}

        >>> _parse_sfnp_template("{{sfnp|Smith|2020|pp=42-45}}")
        {'cite_type': None, 'ref_key': 'Smith', 'pages': '42-45'}
    """
    out = {'cite_type': None}

    # Get location indicators for sfnp templates
    location_keywords = LOC_PARAMS.get(language, LOC_PARAMS['en']).get('sfnp', [])

    # Extract parameters
    params = _extract_template_params(wikitext)

    # First positional parameter is the reference key (author)
    if '1' in params:
        out['ref_key'] = params['1']

    # Extract any location indicators
    for key, value in params.items():
        if key.lower() in location_keywords:
            out[key.lower()] = value

    return out


def is_templated_ref(wikitext: str) -> bool:
    """Determine if a reference is templated or not.
    Match the presence of '{{' and '}}' opening and closing the stripped wikitext.
    """
    if not wikitext:
        return False
    stripped = wikitext.strip()
    return stripped.startswith("{{") and stripped.endswith("}}")

def which_cite_template(wikitext: str) -> Optional[str]:
    """Identify which cite template is used in the wikitext, if any.
    Match {{ cite ... | ...}} using regex, allowing for variations in spacing and case.
    """
    pattern = r"\{\{\s*(cite[^|}]*?)\s*[|}]"
    match = re.search(pattern, wikitext, re.IGNORECASE)
    if match:
        return re.sub(r'\s+', ' ', match.group(1)).strip().lower()
    return None


def _determine_ref_type(ref: dict) -> str:
    """Determine the reference type: main, repeated, repeated_rp, r, rp, sfn, or sfnp.

    - "main": Named reference tag that opens a definition (not self-closing)
    - "repeated": Named reference tag that reuses a main definition (self-closing, no rp)
    - "repeated_rp": Named reference tag that reuses main and has {{rp|...}} location override
    - "r": Standalone {{r|...}} template reference
    - "rp": Standalone {{rp|...}} template reference
    - "sfn": Standalone {{sfn|...}} shortened footnote template
    - "sfnp": Standalone {{sfnp|...}} shortened footnote page template

    Args:
        ref: Reference record from citations NDJSON with ref_kind, ref_self_closing, ref_name

    Returns:
        One of: "main", "repeated", "repeated_rp", "r", "rp", "sfn", "sfnp"
    """
    ref_kind = ref.get('ref_kind')

    if ref_kind == 'r_template':
        return 'r'
    elif ref_kind == 'sfn_template':
        return 'sfn'
    elif ref_kind == 'sfnp_template':
        return 'sfnp'
    elif ref_kind == 'harv_template':
        return 'harv'
    elif ref_kind == 'ref_tag+rp':
        # Repeated ref with {{rp|...}} location override
        return 'repeated_rp'
    elif ref_kind == 'ref_tag':
        # Distinguish between main and repeated based on self_closing and name
        is_self_closing = ref.get('ref_self_closing', False)
        has_name = ref.get('ref_name') is not None

        if has_name:
            return 'repeated' if is_self_closing else 'main'
        else:
            # Unnamed inline refs are treated as main
            return 'main'
    else:
        return 'main'  # Default
