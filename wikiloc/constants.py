"""Locator vocabulary and identifier aliases for the wikiloc parser.

Dependency-free by design: this module is pure data (plain dicts / lists / sets)
and imports nothing outside the standard library, so it can be reused without
pulling in the analysis stack (pandas, matplotlib, ...).

Extending coverage:
- New language      -> add a ``LOC_PARAMS[lang]`` mapping of template name -> locators.
- New locator       -> append the parameter alias to the relevant template's list.
- New identifier    -> add an alias -> canonical mapping in ``ID_ALIASES`` (and, for
                       free-text detection, a pattern in ``_extract_ids_from_text``).
"""

# Canonical identifier aliases for cite templates
# Maps variant parameter names to canonical keys (case-insensitive lookup)
ID_ALIASES = {
    "isbn": "isbn", "isbn13": "isbn", "isbn10": "isbn",
    "doi": "doi",
    "pmid": "pmid",
    "pmc": "pmc",
    "arxiv": "arxiv", "eprint": "arxiv",
}

# Location indicator keywords by reference type and language
# Used to identify location-related parameters in references
#
# English per-template lists derived from Wikipedia CS1 documentation:
#   https://en.wikipedia.org/wiki/Template:Cite_book  (etc.)
# and validated against actual parameter usage in citation data.

# Shared CS1 core: all cite templates accept these
_EN_CORE = [
    "page", "p", "pages", "pp", "at",
    "quote", "q", "quotation",
    "quote-page", "quotepage", "qp", "quotation-page",
    "quote-pages", "quotepages", "qpp", "quotation-pages",
    "quote-location", "quote-loc", "quotation-location", "quote-at",
]

LOC_PARAMS = {
    'en': {
        # -- Books & book-like --
        'cite book': _EN_CORE + [
            "chapter", "contribution", "section",       # https://en.wikipedia.org/wiki/Template:Cite_book
        ],
        'cite encyclopedia': _EN_CORE + [
            "chapter", "contribution", "section",       # https://en.wikipedia.org/wiki/Template:Cite_encyclopedia
            "entry", "article", "department",
        ],
        'cite thesis': _EN_CORE + [
            "chapter", "section",                       # https://en.wikipedia.org/wiki/Template:Cite_thesis
        ],
        'cite report': _EN_CORE + [
            "chapter", "section", "department",         # https://en.wikipedia.org/wiki/Template:Cite_report
            "time", "minutes",
        ],

        # -- Periodicals --
        'cite journal': _EN_CORE + [
            "department",                               # https://en.wikipedia.org/wiki/Template:Cite_journal
        ],
        'cite magazine': _EN_CORE + [
            "department",                               # https://en.wikipedia.org/wiki/Template:Cite_magazine
            "time", "minutes",
        ],
        'cite news': _EN_CORE + [
            "department",                               # https://en.wikipedia.org/wiki/Template:Cite_news
            "time", "minutes",
        ],
        'cite conference': _EN_CORE + [
            "department",                               # https://en.wikipedia.org/wiki/Template:Cite_conference
        ],
        'cite arxiv': _EN_CORE,                         # no extra locators

        # -- Web & social --
        'cite web': _EN_CORE + [
            "department",                               # https://en.wikipedia.org/wiki/Template:Cite_web
        ],
        'cite tweet': ["quote"],                        # atomic source, no page concept
        'cite instagram': ["quote"],

        # -- AV & media --
        'cite av media': _EN_CORE + [
            "chapter", "time", "minutes",               # https://en.wikipedia.org/wiki/Template:Cite_AV_media
        ],
        'cite episode': _EN_CORE + [
            "season", "series-no",                      # https://en.wikipedia.org/wiki/Template:Cite_episode
            "time", "minutes",
        ],
        'cite podcast': _EN_CORE + [
            "time", "minutes",                          # https://en.wikipedia.org/wiki/Template:Cite_podcast
        ],
        'cite speech': _EN_CORE + [
            "time", "minutes",                          # https://en.wikipedia.org/wiki/Template:Cite_speech
        ],
        'cite interview': _EN_CORE + [
            "time", "minutes",                          # https://en.wikipedia.org/wiki/Template:Cite_interview
        ],
        'cite video game': [                            # https://en.wikipedia.org/wiki/Template:Cite_video_game
            "level", "scene", "quote",
            "quote-page", "quote-pages",
        ],

        # -- Maps --
        'cite map': _EN_CORE + [
            "section", "sections",                      # https://en.wikipedia.org/wiki/Template:Cite_map
            "sheet", "sheets", "inset",
        ],

        # -- Legal --
        'cite court': [                                 # https://en.wikipedia.org/wiki/Template:Cite_court
            "pinpoint", "opinion",
            "quote",
        ],
        'cite legislation': [
            "article", "section", "page", "pages",
        ],
        'cite hansard': _EN_CORE,

        # -- Patent (no locators) --
        'cite patent': [],                              # https://en.wikipedia.org/wiki/Template:Cite_patent

        # Fallback for any unlisted 'cite ...' template
        'cite': _EN_CORE + [
            "chapter", "contribution", "entry", "article", "section",
            "department",
            "pinpoint", "opinion",
            "level", "scene",
            "time", "minutes",
            "sheet", "sheets", "inset",
            "season", "series-no",
        ],

        # CS2 generic citation template {{citation}} — same locators as the CS1 core.
        'citation': _EN_CORE + [
            "chapter", "contribution", "entry", "article", "section", "department",
        ],

        # -- Non-cite templates --
        'rp': ["page", "p", "pages", "pp", "chapter", "section"],
        'r': ["page", "p", "pages", "pp", "chapter", "section"],
        'sfn': ["page", "p", "pages", "pp", "at", "loc"],
        'sfnp': ["page", "p", "pages", "pp", "at", "loc"],
        # Harvard author–date short-cite family ({{harvnb}}, {{harvtxt}}, {{harvp}},
        # {{harv}}, {{harvcol*}}, {{harvs}}) — short footnotes carrying page locators.
        'harv': ["page", "p", "pages", "pp", "at", "loc"],
    },
    'fr': {
        'Ouvrage': ['partie', 'numéro', 'numéro chapitre', 'titre chapitre', "chap", "chapter", "passage", "page", "extrait"], # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Ouvrage#Passages
        'Lien web': ['page', 'citation'],  # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Lien_web#Param%C3%A8tres
        'Article': ['page' , 'pages', 'p.', 'pp.', 'passage', 'numéro', 'article', 'extrait', 'quote'], # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Article#Param%C3%A8tre_de_l'emplacement_d'un_passage
        'Chapitre': ['partie', 'passage', 'page debut chapitre', 'extrait'], # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Chapitre
        'Lien arXiv': [], # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Lien_arXiv
        'Lien vidéo': ['temps', 'extrait'], # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Lien_vid%C3%A9o#Param%C3%A8tres
        'Livret album': ['page'], # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Livret_album
        'Brevet': [], # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Brevet
        'Magazine': ['page'], # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Magazine
        "Lien conférence": ['passage', 'page', 'pages', 'extrait'],  # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Lien_conf%C3%A9rence#Param%C3%A8tres
        'Interview': ['position'], # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Interview
        'Article encyclopédique': ['passage', 'page', 'citation', 'quote', 'extrait'], # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Article_encyclop%C3%A9dique#Param%C3%A8tres
        'Citation épisode': [],  # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Citation_%C3%A9pisode#Param%C3%A8tres
        'Cite archive': ['section', 'pièce', 'item'],  # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Cite_archive#Param%C3%A8tres
        'cite report': ['page', 'pages', 'passages', 'quote', 'extrait'],  # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Cite_report#Param%C3%A8tres
        'Bibliographie': ['page'], # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Bibliographie#Comment_remplir_l'%C3%A9l%C3%A9ment_Wikidata
        'Citation jeu vidéo': ['niveau', 'extrait', 'dialogue'], # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Citation_jeu_vid%C3%A9o#TemplateData
        'DVDBibliographie': ['numéro épisode', 'titre épisode', 'passage'],  # https://fr.wikipedia.org/wiki/Mod%C3%A8le:DVDBibliographie#Syntaxe_compl%C3%A8te
        'Écrit': [], # 'pages' fait référence au nombre de pages de la première publication
        'Extrait_vidéo': ['passage'], # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Extrait_vid%C3%A9o#Explication_des_param%C3%A8tres
        'Jugement': ['page', 'paragraphe'],  # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Jugement#TemplateData
        'Loi': ['article', 'référence'], # https://fr.wikipedia.org/wiki/Mod%C3%A8le:Loi#Syntaxe
        'Note discographique': ['citation', 'page'], # https://fr.wikipedia.org/wiki/Sp%C3%A9cial:Modifications_r%C3%A9centes
        'Référence Harvard': ['p', 'loc', 'pp', 'passage', 'pages'],  # https://fr.wikipedia.org/wiki/Mod%C3%A8le:R%C3%A9f%C3%A9rence_Harvard#Param%C3%A8tres
        'Référence Harvard sans parenthèses': ['p', 'loc', 'pp', 'passage', 'pages'],
        'harv': ['p', 'loc', 'pp', 'passage', 'pages'],

        'rp': ["page", "pages", 'at'],   # page would also be the first unnamed argument. — following a <ref> — https://fr.wikipedia.org/wiki/Mod%C3%A8le:Rp#Utilisation

        'sfn': ["p","pp", 'loc'],  # outside of <ref>
        'sfnp': ["p","pp",'loc'], # outside of <ref>
    }
}

# Harvard author–date short-cite templates (normalized, lowercase). Treated like
# {{sfn}}: short footnotes carrying page locators. All variants collapse to 'harv'.
HARV_TEMPLATES = {
    "harvnb", "harv", "harvtxt", "harvp",
    "harvcol", "harvcolnb", "harvcoltxt", "harvcols", "harvs",
}
