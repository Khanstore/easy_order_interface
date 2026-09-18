# -*- coding: utf-8 -*-
"""Fuzzy/phonetic/translation product-name matching, shared between the
public search endpoint (controllers/main.py) and the backend
"suggest a product" feature on Easy Order request lines
(models/easy_order_request.py). Pure Python — no `odoo` imports — so it
can be imported from either a controller or a model without creating a
dependency in the wrong direction.
"""
import re
import unicodedata

# Common spelling variance in Bengali romanization — the same word gets
# transliterated differently depending on who typed it ("Foujdari" vs
# "Fouzdari", "Shirajul" vs "Sirajul"). Folding both the search query and
# each product's name through this table before comparing lets those
# variants match each other. Longer patterns are listed before the
# shorter ones they contain (e.g. "chh" before "ch") so they get folded
# first.
_TRANSLITERATION_FOLDS = [
    ('chh', 'c'), ('kh', 'k'), ('gh', 'g'), ('ch', 'c'), ('jh', 'j'),
    ('th', 't'), ('dh', 'd'), ('bh', 'b'), ('ph', 'f'), ('sh', 's'),
    ('ng', 'n'), ('z', 'j'), ('v', 'b'), ('w', 'b'),
    ('oo', 'u'), ('ee', 'i'), ('aa', 'a'),
]

# Cross-language synonyms: each inner list is a group of words that mean
# the same thing across English and Bengali, so searching in either
# language finds the same items — e.g. typing "police" also matches
# products/categories written as "পুলিশ", and vice versa. This is a
# STARTER list seeded from the categories visible in this catalog today
# (Book, Flags, Uniform, Translation, Publications, Authors, Safety
# Items, Brand, Sports, Life Style, Police) — it is deliberately a plain
# Python list rather than a database model so it's easy to keep
# extending as new categories/products get added, without needing a
# whole translation-management UI for what is, realistically, a few
# dozen entries. Add a new inner list for any word this catalog uses
# that customers might search for in either language.
_TRANSLATION_GLOSSARY = [
    ['police', 'পুলিশ'],
    ['book', 'books', 'বই'],
    ['flag', 'flags', 'পতাকা'],
    ['uniform', 'uniforms', 'ইউনিফর্ম', 'ইউনিফরম'],
    ['translation', 'translations', 'অনুবাদ'],
    ['publication', 'publications', 'প্রকাশনা'],
    ['author', 'authors', 'লেখক'],
    ['safety', 'নিরাপত্তা', 'সেফটি'],
    ['brand', 'brands', 'ব্র্যান্ড'],
    ['sport', 'sports', 'খেলা', 'স্পোর্টস'],
    ['lifestyle', 'life style', 'জীবনধারা'],
    ['fiction', 'ফিকশন'],
    ['mystery', 'রহস্য'],
    ['romance', 'romantic', 'রোমান্স'],
]


def _normalize_search_text(text):
    """Folds text (Bengali script or English/Romanized) down to a rough
    phonetic key so common transliteration spelling variants match each
    other — e.g. "Foujdari" vs "Fouzdari".

    This is a practical heuristic for Bengali romanization variance, not
    a real phonetic algorithm. Module-level (not a method) since it has
    no dependency on controller state and the search glossary below is
    normalized through it once at import time.
    """
    if not text:
        return ''
    text = unicodedata.normalize('NFC', text).lower()
    # Strip punctuation, but keep the whole Bengali Unicode block
    # (\u0980-\u09FF) explicitly: Python's \w only matches "letter"
    # characters, not combining marks — and Bengali vowel signs
    # (matras) and the virama/hasant are combining marks. Without this,
    # a word like পুলিশ silently loses its vowel signs and becomes an
    # unrelated-looking পলশ before it's ever compared to anything.
    text = re.sub(r'[^\w\s\u0980-\u09FF]', '', text)
    for pattern, replacement in _TRANSLITERATION_FOLDS:
        text = text.replace(pattern, replacement)
    text = re.sub(r'(.)\1+', r'\1', text)  # collapse doubled letters
    return re.sub(r'\s+', ' ', text).strip()


def _tokenize(text):
    return [tok for tok in _normalize_search_text(text).split(' ') if tok]


# The glossary above, normalized once at import time: a dict from every
# normalized word to the set of normalized words (including itself) it
# should also match. Built here rather than per-request since it never
# changes while the process is running.
_NORMALIZED_GLOSSARY = {}
# A second index, keyed the same way, but holding the original LITERAL
# spellings (not folded/normalized) — ilike at the database level matches
# actual stored text, so the SQL prefilter in easy_order_search (see
# below) needs real spellings like "পুলিশ", not a normalized key that
# never appears in any real product name.
_LITERAL_GLOSSARY = {}
for _group in _TRANSLATION_GLOSSARY:
    _normalized_group = {
        norm for word in _group
        for norm in [_normalize_search_text(word)] if norm
    }
    for _word in _normalized_group:
        _NORMALIZED_GLOSSARY.setdefault(_word, set()).update(_normalized_group)
        _LITERAL_GLOSSARY.setdefault(_word, set()).update(_group)


def _edit_distance(a, b):
    """Damerau-Levenshtein distance (restricted/OSA variant): like plain
    edit distance, but counts swapping two adjacent letters — the single
    most common kind of typo (e.g. "Zakri" for "Zakir") — as ONE edit
    instead of two. Used as a small, deliberately narrow safety net for
    typos/phonetic slips the transliteration folds don't already cover;
    see _word_matches_score for how far it's allowed to reach.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(
                d[i - 1][j] + 1,        # deletion
                d[i][j - 1] + 1,        # insertion
                d[i - 1][j - 1] + cost,  # substitution
            )
            if (
                i > 1 and j > 1
                and a[i - 1] == b[j - 2]
                and a[i - 2] == b[j - 1]
            ):
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + cost)  # transposition
    return d[la][lb]


def _word_matches_score(query_word, name_tokens):
    """How well one query word (already expanded to its glossary
    variants by the caller) matches anywhere in a product's searchable
    tokens. 0 means no match at all.
    """
    best = 0
    # A one-letter token is too unspecific for prefix/substring/fuzzy
    # matching to mean anything — without this, a short or heavily-
    # repeated query like "zzz" can fold down to a single letter (via
    # the z->j translit fold plus doubled-letter collapse) and then
    # "match" almost any product that happens to contain that letter.
    if len(query_word) < 2:
        return 3 if query_word in name_tokens else 0
    for nt in name_tokens:
        if query_word == nt:
            return 3  # exact token match — nothing beats this
        if nt.startswith(query_word) or query_word.startswith(nt):
            best = max(best, 2)  # one is a prefix of the other
        elif query_word in nt or nt in query_word:
            best = max(best, 1)  # substring either way
        else:
            # How many typos/phonetic slips to tolerate scales with word
            # length, so a short word can't fuzzy-match something
            # unrelated just because they happen to share a couple of
            # letters.
            shorter = min(len(query_word), len(nt))
            if shorter >= 7:
                allowed = 2
            elif shorter >= 4:
                allowed = 1
            else:
                allowed = 0
            if allowed and _edit_distance(query_word, nt) <= allowed:
                best = max(best, 1)
    return best


def _score_product(query_word_groups, name_tokens, categ_tokens):
    """Every word the person typed must find at least a partial match
    somewhere in the product's own name OR its category names (AND
    across words, OR within a word's translation variants and OR
    between name/category) — but a match found only in a category name
    counts for HALF as much as one found in the product's own name.

    Without that distinction, searching a broad category name like
    "book" would rank every single book in that category exactly as
    high as a book actually titled "Book of ..." — which feels
    scattershot rather than "to the point". Category matches still
    count (so browsing-by-category-word still works), they just don't
    outrank an actual name match.
    """
    total = 0
    for group in query_word_groups:
        name_best = max((_word_matches_score(w, name_tokens) for w in group), default=0)
        categ_best = max((_word_matches_score(w, categ_tokens) for w in group), default=0)
        best = max(name_best, categ_best * 0.5)
        if best == 0:
            return 0
        total += best
    return total
