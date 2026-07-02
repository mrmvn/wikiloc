"""wikiloc — parse in-source locators from Wikipedia citation wikitext.

An *in-source location* is the specific part of a source that supports a
statement — a page, a page range, a chapter or a quotation. Editors record these
through dedicated citation-template parameters (``page``, ``pages``, ``chapter``,
``quote``, …), which we call *locators*. ``wikiloc`` parses the locators (and
identifiers) declared by a single reference, using the exact set of parameters
each citation template authorises.

Primary entry point — pass one reference's wikitext:

    >>> from wikiloc import parse
    >>> parse("{{cite book|title=X|isbn=978-0-13-468599-1|page=42}}")
    {'cite_type': 'cite book', 'locators': {'page': '42'}, 'ids': {'isbn': '978-0-13-468599-1'}}

English is the default; French is included and more languages can be added by
extending :data:`wikiloc.constants.LOC_PARAMS`. See the README for details.

This is the standalone release of the parser used in the study "Citation
Location Needed"; whole-article extraction and named-reference reconciliation
are intentionally out of scope (see the project pipeline for those).
"""

from .parser import parse, parse_reference
from .constants import LOC_PARAMS, ID_ALIASES, HARV_TEMPLATES

__all__ = ["parse", "parse_reference", "LOC_PARAMS", "ID_ALIASES", "HARV_TEMPLATES"]

__version__ = "0.1.0"
