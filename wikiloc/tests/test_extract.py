"""Tests for whole-article reference extraction (``wikiloc.extract``).

Covers WL-2: recursion into nested templates/tags, list-defined references and
name inheritance, per-sibling ``{{rp}}`` adjacency, and the no-double-count /
no-ref-inside-ref guards.
"""

import pytest

pytest.importorskip("mwparserfromhell")

from wikiloc import resolve_references
from wikiloc.extract import extract_references, parse_article


def _names(records):
    return [r.get("ref_name") for r in records]


# --- basic top-level behaviour (regression) -------------------------------

def test_top_level_ref_and_attrs():
    refs = extract_references('<ref name="a" group="note">{{cite book|page=42}}</ref>')
    assert len(refs) == 1
    assert refs[0]["ref_kind"] == "ref_tag"
    assert refs[0]["ref_name"] == "a"
    assert refs[0]["ref_self_closing"] is False


def test_top_level_short_cites_still_collected():
    refs = extract_references("{{sfn|Smith|2020|p=42}} and {{r|Jones2021|page=7}}")
    assert [r["ref_kind"] for r in refs] == ["sfn_template", "r_template"]
    assert _names(refs) == ["Smith", "Jones2021"]


# --- WL-2: nested references ----------------------------------------------

def test_ref_inside_infobox_parameter():
    refs = extract_references("{{Infobox|data=<ref>{{cite book|page=42}}</ref>}}")
    assert len(refs) == 1
    assert resolve_references(refs)[0]["page"] == "42"


def test_ref_two_templates_deep():
    refs = extract_references("{{Outer|{{Inner|x=<ref>{{cite book|page=7}}</ref>}}}}")
    assert len(refs) == 1
    assert resolve_references(refs)[0]["page"] == "7"


def test_ref_inside_non_ref_tag():
    refs = extract_references("<poem><ref>{{cite book|page=3}}</ref></poem>")
    assert len(refs) == 1
    assert resolve_references(refs)[0]["page"] == "3"


def test_list_defined_ref_definition_and_inheritance():
    wikitext = (
        "Text.<ref name=a/>\n"
        "{{reflist|refs=<ref name=a>{{cite book|page=42}}</ref>}}"
    )
    refs = extract_references(wikitext)
    assert len(refs) == 2
    assert refs[0]["ref_self_closing"] is True   # the use comes first
    assert refs[1]["ref_name"] == "a"            # the definition follows
    resolved = resolve_references(refs)
    assert resolved[0]["ref_type"] == "repeated"
    assert resolved[0]["page"] == "42"           # inherited from the definition
    assert resolved[1]["page"] == "42"


def test_list_defined_two_defs_one_reused_with_rp():
    wikitext = (
        "Text.<ref name=b/>{{rp|13}}\n"
        "{{reflist|refs="
        "<ref name=a>{{cite book|page=1}}</ref>"
        "<ref name=b>{{cite book|page=2}}</ref>"
        "}}"
    )
    refs = extract_references(wikitext)
    assert len(refs) == 3
    resolved = resolve_references(refs)
    use = next(r for r in resolved if r["ref_type"] == "repeated_rp")
    assert use["page"] == "13"          # rp override wins over inherited page 2
    assert use["cite_type"] == "cite book"


def test_reflist_definition_collected_without_use():
    refs = extract_references("{{reflist|refs=<ref name=a>{{cite book|page=9}}</ref>}}")
    assert len(refs) == 1
    assert resolve_references(refs)[0]["page"] == "9"


def test_document_order_is_preserved():
    wikitext = (
        "A<ref name=one>{{cite book|page=1}}</ref>"
        "B{{Infobox|x=<ref name=two>{{cite book|page=2}}</ref>}}"
        "C<ref name=three/>"
    )
    assert _names(extract_references(wikitext)) == ["one", "two", "three"]


# --- adjacency rules -------------------------------------------------------

def test_rp_adjacency_stays_within_sibling_sequence():
    # The <ref> is nested in the template; the top-level {{rp}} is not its
    # sibling, so it must not attach.
    refs = extract_references("{{Infobox|data=<ref name=x>{{cite book|page=1}}</ref>}}{{rp|13}}")
    assert len(refs) == 1
    assert refs[0]["ref_kind"] == "ref_tag"
    assert refs[0]["ref_rp_raw"] is None


def test_rp_adjacency_inside_nested_parameter():
    refs = extract_references("{{Infobox|data=<ref>{{cite book|page=1}}</ref>{{rp|13}}}}")
    assert len(refs) == 1
    assert refs[0]["ref_kind"] == "ref_tag+rp"
    assert refs[0]["ref_rp_raw"] == "{{rp|13}}"


def test_rp_adjacency_whitespace_comment_and_text():
    # whitespace keeps the window open
    refs = extract_references("<ref>{{cite book|page=1}}</ref>   {{rp|13}}")
    assert refs[0]["ref_kind"] == "ref_tag+rp"
    # an HTML comment is transparent (WL-6)
    refs = extract_references("<ref>{{cite book|page=1}}</ref><!-- c -->{{rp|13}}")
    assert refs[0]["ref_kind"] == "ref_tag+rp"
    # real inline text breaks it
    refs = extract_references("<ref>{{cite book|page=1}}</ref> some text {{rp|13}}")
    assert refs[0]["ref_kind"] == "ref_tag"


# --- no double counting / no ref-inside-ref -------------------------------

def test_short_cite_inside_ref_not_double_counted():
    refs = extract_references("<ref>{{sfn|Smith|2020|p=42}}{{cite book|page=1}}</ref>")
    assert len(refs) == 1
    assert refs[0]["ref_kind"] == "ref_tag"
    # the inner sfn is parsed as part of the reference
    assert resolve_references(refs)[0]["p"] == "42"


def test_ref_inside_ref_is_ignored():
    refs = extract_references("<ref>outer {{cite book|page=1}}<ref>inner</ref></ref>")
    assert len(refs) == 1
    assert refs[0]["ref_contents"].startswith("outer")


# --- end to end ------------------------------------------------------------

def test_parse_article_with_infobox_and_list_defined_ref():
    wikitext = (
        "{{Infobox|born=<ref name=b>{{cite book|page=12}}</ref>}}\n"
        "Text.<ref name=b/>\n"
        "{{reflist|refs=<ref name=c>{{cite book|page=99}}</ref>}}\n"
        "<ref name=c/>"
    )
    resolved = parse_article(wikitext)
    by_name = {}
    for r in resolved:
        by_name.setdefault(r["ref_name"], []).append(r)
    # infobox definition and its use both carry page 12
    assert all(r["page"] == "12" for r in by_name["b"])
    # reflist definition and its use both carry page 99
    assert all(r["page"] == "99" for r in by_name["c"])


# --- CITEREF resolution ----------------------------------------------------
#
# Short cites ({{sfn}}/{{sfnp}}/Harvard/{{r}}) link to a full CS1/CS2 citation's
# HTML anchor: the explicit |ref= value or the auto-generated
# CITEREF<last-names><year> id. When the link resolves, the short cite inherits
# the full citation's cite_type and identifiers.

def _resolved_by_type(wikitext):
    return {r["ref_type"]: r for r in parse_article(wikitext)}


def test_sfn_inherits_via_auto_citeref_anchor():
    wikitext = (
        "Text.{{sfn|Smith|2020|p=3}}\n"
        "<ref>{{cite book|last=Smith|first=John|year=2020|title=Book"
        "|isbn=978-0-13-468599-1|pages=100-150}}</ref>"
    )
    resolved = _resolved_by_type(wikitext)
    sfn = resolved["sfn"]
    assert sfn["cite_type"] == "cite book"
    assert sfn["isbn"] == "978-0-13-468599-1"
    assert sfn["pages"] == "100-150"     # inherited from the full citation
    assert sfn["p"] == "3"               # the short cite's own pinpoint wins


def test_harvnb_inherits_via_auto_citeref_anchor():
    wikitext = (
        "{{harvnb|Jones|2019|p=7}}\n"
        "<ref>{{cite book|last=Jones|first=A|date=2019|title=J|doi=10.1000/x}}</ref>"
    )
    resolved = _resolved_by_type(wikitext)
    harv = resolved["harv"]
    assert harv["cite_type"] == "cite book"
    assert harv["doi"] == "10.1000/x"
    assert harv["p"] == "7"


def test_sfn_multi_author_citeref_anchor():
    wikitext = (
        "{{sfn|Smith|Jones|2020|p=1}}\n"
        "<ref>{{cite book|last1=Smith|last2=Jones|year=2020|isbn=1-2-3}}</ref>"
    )
    resolved = _resolved_by_type(wikitext)
    assert resolved["sfn"]["cite_type"] == "cite book"
    assert resolved["sfn"]["isbn"] == "1-2-3"


def test_sfn_editor_fallback_citeref_anchor():
    wikitext = (
        "{{sfn|Smith|1999|p=1}}\n"
        "<ref>{{cite book|editor-last=Smith|editor-first=J|date=March 1999|title=E|isbn=1-2-3}}</ref>"
    )
    resolved = _resolved_by_type(wikitext)
    assert resolved["sfn"]["cite_type"] == "cite book"
    assert resolved["sfn"]["isbn"] == "1-2-3"


def test_r_matches_explicit_ref_anchor():
    wikitext = (
        "{{r|Smith2020|p=9}}\n"
        "<ref>{{cite book|title=No author|ref=Smith2020|isbn=978-0-13-468599-1}}</ref>"
    )
    resolved = _resolved_by_type(wikitext)
    assert resolved["r"]["cite_type"] == "cite book"
    assert resolved["r"]["isbn"] == "978-0-13-468599-1"
    assert resolved["r"]["p"] == "9"


def test_sfn_matches_explicit_citeref_ref():
    wikitext = (
        "{{sfn|Smith|2020|p=2}}\n"
        "<ref>{{cite book|last=Smith|year=2020|ref=CITEREFSmith2020|doi=10.1/x}}</ref>"
    )
    resolved = _resolved_by_type(wikitext)
    assert resolved["sfn"]["cite_type"] == "cite book"
    assert resolved["sfn"]["doi"] == "10.1/x"


def test_ref_none_disables_citeref_inheritance():
    wikitext = (
        "{{sfn|Smith|2020|p=3}}\n"
        "<ref>{{cite book|last=Smith|year=2020|ref=none|isbn=978-0-13-468599-1}}</ref>"
    )
    resolved = _resolved_by_type(wikitext)
    assert resolved["sfn"]["cite_type"] is None
    assert "isbn" not in resolved["sfn"]


def test_sfnref_expansion_matches_citeref_anchor():
    wikitext = (
        "{{sfn|Title|1999|p=2}}\n"
        "<ref>{{cite book|title=Title|date=1999|ref={{sfnref|Title|1999}}|isbn=1-2-3}}</ref>"
    )
    resolved = _resolved_by_type(wikitext)
    assert resolved["sfn"]["cite_type"] == "cite book"
    assert resolved["sfn"]["isbn"] == "1-2-3"


def test_ref_harv_forces_auto_citeref_anchor():
    wikitext = (
        "{{sfn|Smith|2020|p=1}}\n"
        "<ref>{{cite book|last=Smith|year=2020|ref=harv|isbn=1-2-3}}</ref>"
    )
    resolved = _resolved_by_type(wikitext)
    assert resolved["sfn"]["cite_type"] == "cite book"
    assert resolved["sfn"]["isbn"] == "1-2-3"


def test_sfnp_inherits_via_citeref_anchor():
    wikitext = (
        "{{sfnp|Smith|2020|p=5}}\n"
        "<ref>{{cite book|last=Smith|year=2020|isbn=1-2-3}}</ref>"
    )
    resolved = _resolved_by_type(wikitext)
    assert resolved["sfnp"]["cite_type"] == "cite book"
    assert resolved["sfnp"]["isbn"] == "1-2-3"
    assert resolved["sfnp"]["p"] == "5"


def test_harvs_inherits_via_named_citeref_anchor():
    wikitext = (
        "{{harvs|txt|last=Smith|year=2020|p=4}}\n"
        "<ref>{{cite book|last=Smith|year=2020|isbn=1-2-3}}</ref>"
    )
    resolved = _resolved_by_type(wikitext)
    assert resolved["harv"]["cite_type"] == "cite book"
    assert resolved["harv"]["isbn"] == "1-2-3"
    assert resolved["harv"]["p"] == "4"
