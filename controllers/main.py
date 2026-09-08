# -*- coding: utf-8 -*-
import re
import unicodedata

from odoo import http
from odoo.http import request
from odoo.exceptions import UserError
from odoo.osv import expression
from odoo.tools.translate import _
from odoo.tools.misc import formatLang

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


class EasyOrderInterface(http.Controller):
    """Controller for the simplified /easy-order browsing experience.

    Structure: /easy-order (a directory of TOP-LEVEL easy.order.category
    tiles) -> /easy-order/<code> (that top-level category's own
    subcategories + products) -> /easy-order/<code>/shop/<subcategory>
    (deeper subcategories + products, recursively). There's no separate
    "group" model — a top-level category (no parent_id) plays that role
    itself: its own `code` becomes its web address, and everything
    nested under it forms one self-contained section with its own
    scoped search. easy.order.category is a fully separate structure
    from the real shop's product.public.category — see
    models/easy_order_category.py for why.

    Cart mutations here deliberately reuse website_sale's own internal
    cart API (website.sale_get_order / sale.order._cart_update) instead
    of writing custom sale.order logic. That keeps this module from
    creating a second, parallel notion of "the current order" that
    could drift out of sync with the standard /shop cart, and it means
    tax/pricelist/stock computation is exactly what the rest of the
    site already relies on.
    """

    def _get_top_level_categories(self):
        return request.env['easy.order.category'].sudo().search([
            ('parent_id', '=', False),
        ])

    def _get_category_by_code_or_404(self, code):
        return request.env['easy.order.category'].sudo().search([
            ('parent_id', '=', False),
            ('code', '=', code),
        ], limit=1)

    def _get_top_ancestor(self, category):
        """Walks up to the top-most category in this tree — the one
        whose `code` the whole section is reached through. A top-level
        category is its own top ancestor.
        """
        top = category
        while top.parent_id:
            top = top.parent_id
        return top

    def _get_category_subtree_ids(self, category):
        """This category's id plus every descendant's id, recursively —
        used to scope search to "this section and everything under it".
        """
        ids = [category.id]
        for child in category.child_ids:
            ids.extend(self._get_category_subtree_ids(child))
        return ids

    def _category_url(self, category, top_code):
        """The one canonical URL for any category in this tree. A
        top-level category gets the short, pretty /easy-order/<code>;
        anything nested gets /easy-order/<top code>/shop/<id> instead —
        `top_code` is passed in rather than recomputed each time since
        callers already know it (it's what's in the current request's
        own URL).
        """
        if not category.parent_id:
            return '/easy-order/%s' % top_code
        return '/easy-order/%s/shop/%s' % (top_code, category.id)

    def _get_category_ancestors(self, category):
        """Ordered list of parent categories from the top down (not
        including `category` itself), for the breadcrumb trail."""
        ancestors = []
        parent = category.parent_id
        while parent:
            ancestors.insert(0, parent)
            parent = parent.parent_id
        return ancestors

    def _get_category_variants(self, category):
        """Sellable variants for the products assigned to this category —
        just category.product_tmpl_ids by default, or also every
        subcategory's products (recursively) if
        category.include_subcategory_products is turned on. Either way,
        safety-filtered on published/sale_ok — a product left assigned
        here after being unpublished or archived elsewhere shouldn't
        still show up.
        """
        if category.include_subcategory_products:
            subtree_ids = self._get_category_subtree_ids(category)
            categories = request.env['easy.order.category'].sudo().browse(subtree_ids)
            template_ids = categories.mapped('product_tmpl_ids').ids
        else:
            template_ids = category.product_tmpl_ids.ids

        if not template_ids:
            return request.env['product.product']
        variants = request.env['product.product'].sudo().search([
            ('product_tmpl_id', 'in', template_ids),
            ('product_tmpl_id.is_published', '=', True),
            ('product_tmpl_id.sale_ok', '=', True),
        ])
        # Sorted by the template's own name (not the variant's combination
        # suffix), so "Part 1" / "Part 2" of the same book stay adjacent
        # rather than being scattered by an alphabetical mix-up with
        # "(Part: 1)" vs "(Part: 2)" suffixes.
        return variants.sorted(key=lambda v: v.product_tmpl_id.name or '')

    def _get_cart_quantity(self):
        order = request.website.sale_get_order()
        return order.cart_quantity if order else 0

    def _get_invoiced_price(self, variant):
        """The price actually charged for this variant — run through
        website_sale's own pricelist/tax computation, the same helper the
        standard /shop page uses.

        Using this instead of list_price/lst_price matters whenever a
        pricelist, a currency other than the company's, or "tax included"
        display is in play: those can all make the raw catalog price
        different from what actually ends up on the order line, and this
        page should always show the number that will be invoiced.
        """
        info = variant.product_tmpl_id._get_combination_info(
            combination=variant.product_template_attribute_value_ids,
            product_id=variant.id,
        )
        return info['price']

    def _is_out_of_stock(self, variant):
        """True if this variant is a tracked/storable product with no
        stock left and "Continue Selling" (allow_out_of_stock_order) is
        off — the same rule website_sale itself uses to decide whether
        Add to Cart should still work.

        Both `is_storable` and `free_qty` only exist when the 'stock'
        app is installed, so this checks the fields are actually there
        first rather than assuming — a shop running sales without
        Inventory installed should never have every product wrongly
        treated as out of stock.
        """
        template = variant.product_tmpl_id
        if 'is_storable' not in template._fields or not template.is_storable:
            return False
        if template.allow_out_of_stock_order:
            return False
        if 'free_qty' not in variant._fields:
            return False
        return variant.free_qty <= 0

    def _get_popular_variants(self, variants, limit=6):
        """The best-selling variants among `variants`, based on actual
        confirmed order history — not a manual "featured" flag, since
        this catalog has no such field and a real sales count is more
        trustworthy than a guess. Returns an empty recordset (so the
        "Popular" row just doesn't render) if there's no order history
        yet, e.g. a brand-new category.
        """
        if not variants:
            return variants
        groups = request.env['sale.order.line'].sudo().read_group(
            domain=[
                ('product_id', 'in', variants.ids),
                ('order_id.state', 'in', ['sale', 'done']),
            ],
            fields=['product_id', 'product_uom_qty:sum'],
            groupby=['product_id'],
            orderby='product_uom_qty desc',
            limit=limit,
        )
        ordered_ids = [g['product_id'][0] for g in groups if g.get('product_id')]
        # Preserve the popularity order read_group already gave us —
        # variants.browse(ids) does NOT do this on its own, it returns
        # records in the recordset's natural (id) order instead.
        by_id = {v.id: v for v in variants}
        return variants.browse([]).union(*(
            by_id[vid] for vid in ordered_ids if vid in by_id
        ))

    def _get_support_phone(self):
        """Phone/WhatsApp number for the "Call to order" button, set via
        Settings > Technical > System Parameters
        (easy_order_interface.support_phone) rather than hard-coded, so
        it can be configured — or left blank to hide the button
        entirely — without touching code. Expected format: digits only,
        with country code, no leading '+' (e.g. "8801XXXXXXXXX").
        """
        return request.env['ir.config_parameter'].sudo().get_param(
            'easy_order_interface.support_phone', ''
        ).strip()

    @http.route(
        '/easy-order', type='http', auth='public', website=True,
        sitemap=True,
    )
    def easy_order_home(self, **kwargs):
        """Top-level category directory — the very first thing anyone
        sees. Picking one (e.g. পুলিশ) takes them to that section's own
        subcategories/products at /easy-order/<code>.
        """
        values = {
            'categories': self._get_top_level_categories(),
            'cart_qty': self._get_cart_quantity(),
            'support_phone': self._get_support_phone(),
        }
        return request.render('easy_order_interface.page_categories', values)

    def _render_category_page(self, category, top_code):
        subcategories = category.child_ids
        # This lists actual sellable variants (product.product), not
        # templates: a book sold as "Part 1" / "Part 2" shows as two
        # separate rows, each with its own photo, price, and Add to Cart
        # button, rather than one row with a dropdown to choose between
        # them. For a person unfamiliar with online shopping, tapping the
        # right card is a lot more direct than picking an option first.
        variants = self._get_category_variants(category)
        product_prices = {
            variant.id: self._get_invoiced_price(variant) for variant in variants
        }
        product_out_of_stock = {
            variant.id: self._is_out_of_stock(variant) for variant in variants
        }
        popular_variants = self._get_popular_variants(variants)
        ancestors = self._get_category_ancestors(category)
        back_url = (
            '/easy-order' if not category.parent_id
            else self._category_url(category.parent_id, top_code)
        )
        values = {
            'top_code': top_code,
            'category': category,
            'category_url': self._category_url(category, top_code),
            'ancestor_links': [
                {'category': anc, 'url': self._category_url(anc, top_code)}
                for anc in ancestors
            ],
            'back_url': back_url,
            'subcategories': subcategories,
            'products': variants,
            'popular_products': popular_variants,
            'product_prices': product_prices,
            'product_out_of_stock': product_out_of_stock,
            'cart_qty': self._get_cart_quantity(),
            'support_phone': self._get_support_phone(),
        }
        return request.render('easy_order_interface.page_products', values)

    @http.route(
        '/easy-order/<string:code>', type='http', auth='public',
        website=True, sitemap=True,
    )
    def easy_order_top_category(self, code, **kwargs):
        category = self._get_category_by_code_or_404(code)
        if not category:
            return request.not_found()
        return self._render_category_page(category, code)

    @http.route(
        '/easy-order/<string:code>/shop/'
        '<model("easy.order.category"):category>',
        type='http', auth='public', website=True, sitemap=True,
    )
    def easy_order_subcategory(self, code, category, **kwargs):
        top = self._get_top_ancestor(category)
        if not top.code or top.code != code:
            # The code in the URL doesn't match this category's actual
            # top-level ancestor — either a stale/guessed link, or the
            # category has since been moved under a different section.
            return request.not_found()
        return self._render_category_page(category, code)

    def _build_search_domain(self, query, category_subtree_ids):
        """A fast, broad SQL ilike net cast BEFORE the precise Python
        scoring in easy_order_search — narrows "every product assigned
        anywhere in this section" down to "plausibly relevant ones"
        cheaply, so the expensive fuzzy/translation logic only runs on a
        small candidate set instead of everything in the section on
        every keystroke.

        Deliberately over-inclusive (OR across every raw query word, its
        glossary translations, matched against both the product's own
        name and its Easy Order category names): the Python stage
        afterward still enforces that every word in the query actually
        matches (AND) — this stage only needs to not accidentally
        exclude a real match, not to be precise.
        """
        raw_words = [w for w in re.split(r'\s+', query.strip()) if w]
        terms = set()
        for word in raw_words:
            terms.add(word)
            terms |= _LITERAL_GLOSSARY.get(_normalize_search_text(word), set())

        term_domains = []
        for term in terms:
            term_domains.append([('name', 'ilike', term)])
            term_domains.append([
                ('product_tmpl_id.easy_order_category_ids.name', 'ilike', term),
            ])
            term_domains.append([
                ('product_tmpl_id.easy_order_category_ids.public_name', 'ilike', term),
            ])

        return expression.AND([
            [
                ('product_tmpl_id.is_published', '=', True),
                ('product_tmpl_id.sale_ok', '=', True),
                ('product_tmpl_id.easy_order_category_ids', 'in', category_subtree_ids),
            ],
            expression.OR(term_domains),
        ])

    @http.route(
        '/easy-order/<string:code>/search', type='json',
        auth='public', website=True,
    )
    def easy_order_search(self, code, query='', **kwargs):
        """Backs the live search box. Scoped to the CURRENT top-level
        section only — searching from within /easy-order/police/...
        only searches products assigned somewhere under পুলিশ, not the
        whole catalog, so each section keeps feeling like its own
        self-contained storefront rather than a filtered view of
        everything.

        Two stages, for speed:
          STAGE 1 — a cheap SQL ilike prefilter (see _build_search_domain)
          narrows this section's products down to a plausible candidate
          set before touching Python at all. This is what makes the
          endpoint fast: without it, every keystroke was scoring every
          single published variant in Python, however large the catalog.
          STAGE 2 — the candidates from stage 1 are ranked in Python with
          the full matching logic:
          1. Transliteration folding (module-level _normalize_search_text)
             — spelling variants of the same Romanized word collapse to
             the same key, e.g. "Foujdari" / "Fouzdari".
          2. Cross-language synonyms (_TRANSLATION_GLOSSARY) — a query
             word is also checked against its known translations, so
             "police" matches items tagged/named "পুলিশ" and back again.
          3. Per-token fuzzy matching (_word_matches_score) — exact token
             match beats a prefix match beats a substring match beats a
             one-letter edit-distance match, so results are ranked by how
             good the match actually is instead of all appearing equal.

        A product's searchable tokens include its own name AND the names
        of the Easy Order categories it's assigned to — searching
        "police" finds products filed under a পুলিশ-tagged category even
        if the product's own title doesn't contain that word.
        """
        top = self._get_category_by_code_or_404(code)
        if not top:
            return {'results': []}

        query = (query or '').strip()
        if not query:
            return {'results': []}

        # Each query word expands to itself plus any known translations/
        # synonyms — e.g. "police" also expands to "পুলিশ" (and vice
        # versa), so either spelling finds the same items.
        query_word_groups = [
            _NORMALIZED_GLOSSARY.get(word, {word})
            for word in _tokenize(query)
        ]
        if not query_word_groups:
            return {'results': []}

        subtree_ids = self._get_category_subtree_ids(top)
        domain = self._build_search_domain(query, subtree_ids)
        # Capped so one very common word (e.g. "book") can't drag this
        # whole section's catalog into the Python scoring stage on its
        # own — 300 is comfortably above what any real search needs,
        # since only the top 40 best-scored results ever get returned
        # anyway.
        variants = request.env['product.product'].sudo().search(domain, limit=300)

        scored = []
        for variant in variants:
            categories = variant.product_tmpl_id.easy_order_category_ids
            # Both fields — a search for "law books" (internal) and one
            # for "books" (the shared display name) should both be able
            # to find the same product.
            categ_names = categories.mapped('name') + categories.mapped('public_name')
            name_tokens = _tokenize(variant.display_name)
            categ_tokens = []
            for categ_name in categ_names:
                categ_tokens.extend(_tokenize(categ_name))
            score = _score_product(query_word_groups, name_tokens, categ_tokens)
            if score:
                scored.append((score, variant))

        # Best matches first; ties broken alphabetically by the
        # template's own name (not the variant's combination suffix), so
        # "Part 1" / "Part 2" of the same book stay adjacent.
        scored.sort(key=lambda pair: (-pair[0], pair[1].product_tmpl_id.name or ''))
        matches = [variant for _score, variant in scored]

        results = []
        for variant in matches[:40]:
            price = self._get_invoiced_price(variant)
            results.append({
                'variant_id': variant.id,
                'template_id': variant.product_tmpl_id.id,
                'name': variant.display_name,
                'price_formatted': formatLang(
                    request.env, price, currency_obj=variant.currency_id,
                ),
                'image_url': '/web/image/product.product/%s/image_128' % variant.id,
                'out_of_stock': self._is_out_of_stock(variant),
            })
        return {'results': results}

    @http.route(
        '/easy-order/cart/add', type='json', auth='public', website=True,
        csrf=True,
    )
    def easy_order_add_to_cart(self, product_id, qty=1, variant_id=None, **kwargs):
        try:
            product_id = int(product_id)
            qty = float(qty)
        except (TypeError, ValueError):
            return {'error': _("এই পরিমাণটি ঠিক মনে হচ্ছে না।")}

        if qty <= 0:
            return {'error': _("অন্তত ১টি পরিমাণ বেছে নিন।")}

        product = request.env['product.template'].sudo().browse(product_id)
        if not product.exists() or not product.is_published:
            return {'error': _("দুঃখিত, এই পণ্যটি এখন পাওয়া যাচ্ছে না।")}

        if variant_id:
            try:
                variant_id = int(variant_id)
            except (TypeError, ValueError):
                return {'error': _("এই পণ্যের জন্য একটি অপশন বেছে নিন।")}
            variant = request.env['product.product'].sudo().browse(variant_id)
            # Trusting the variant_id the page sends is only safe once it's
            # confirmed to actually be one of this template's own variants —
            # otherwise a tampered request could add an unrelated product.
            if (
                not variant.exists()
                or not variant.active
                or variant.product_tmpl_id.id != product.id
            ):
                return {'error': _("এই পণ্যের জন্য সঠিক অপশন বেছে নিন।")}
        else:
            variant = product.product_variant_id
            if len(product.product_variant_ids) > 1:
                # More than one option exists and none was specified — this
                # is what used to happen silently before: the page had no
                # selector at all, so it always fell through to whichever
                # variant Odoo picked as the default.
                return {'error': _("কার্টে যোগ করার আগে একটি অপশন বেছে নিন।")}
            if not variant:
                # A template with no created variant has nothing to add a
                # line for. Without this check _cart_update below silently
                # receives product_id=False and the click just does
                # nothing, with no error shown.
                return {'error': _("দুঃখিত, এই পণ্যটি এখন পাওয়া যাচ্ছে না।")}

        order = request.website.sale_get_order(force_create=True)
        try:
            order._cart_update(product_id=variant.id, add_qty=qty)
        except UserError as e:
            # Surfaces things like "out of stock" in plain language rather
            # than a generic failure. NOTE: this message comes straight
            # from Odoo's own stock/sale logic, so it stays in whatever
            # language Odoo itself is running in — it isn't one of this
            # module's own hardcoded Bengali strings.
            return {'error': str(e)}
        except Exception:
            # Anything unexpected still gets a message in front of the
            # person instead of the button just doing nothing, which is
            # what a bare exception here looks like from the UI.
            return {'error': _("দুঃখিত, কার্টে যোগ করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।")}

        order_sudo = order.sudo()
        return {
            'cart_qty': order_sudo.cart_quantity,
            'cart_total': order_sudo.amount_total,
        }

    @http.route(
        '/easy-order/request', type='http', auth='public', website=True,
    )
    def easy_order_request_form(self, **kwargs):
        """"Can't find it? Tell us" — for anyone who'd rather just say
        what they want in their own words than browse/search the
        catalog. Nothing here is matched to a real product yet; a staff
        member reviews and converts it to a real order afterward (see
        easy.order.request.action_create_sale_order and the backend
        views in views/easy_order_request_views.xml).
        """
        return request.render('easy_order_interface.page_request_form', {
            'cart_qty': self._get_cart_quantity(),
            'support_phone': self._get_support_phone(),
        })

    @http.route(
        '/easy-order/request/submit', type='http', auth='public',
        website=True, methods=['POST'], csrf=True,
    )
    def easy_order_request_submit(self, **post):
        customer_name = (post.get('customer_name') or '').strip()
        phone = (post.get('phone') or '').strip()
        address = (post.get('address') or '').strip()

        # Repeated field names (one "item_name"/"item_qty" pair per row
        # the person added) need the raw Werkzeug form object's
        # getlist() — Odoo's own **kwargs merging isn't guaranteed to
        # keep more than the last value for a repeated field name.
        item_names = request.httprequest.form.getlist('item_name')
        item_qtys = request.httprequest.form.getlist('item_qty')

        lines = []
        for name, qty_str in zip(item_names, item_qtys):
            name = (name or '').strip()
            if not name:
                continue
            try:
                qty = float(qty_str)
            except (TypeError, ValueError):
                qty = 1.0
            if qty <= 0:
                qty = 1.0
            lines.append((0, 0, {'probable_name': name, 'qty': qty}))

        error = None
        if not customer_name:
            error = _("আপনার নাম লিখুন।")
        elif not phone:
            error = _("আপনার ফোন নম্বর লিখুন।")
        elif not lines:
            error = _("আপনি কী খুঁজছেন অন্তত একটি জিনিস লিখুন।")

        if error:
            return request.render('easy_order_interface.page_request_form', {
                'cart_qty': self._get_cart_quantity(),
                'support_phone': self._get_support_phone(),
                'error': error,
                'form_values': post,
            })

        request.env['easy.order.request'].sudo().create({
            'customer_name': customer_name,
            'phone': phone,
            'address': address,
            'line_ids': lines,
        })

        return request.render('easy_order_interface.page_request_thanks', {
            'cart_qty': self._get_cart_quantity(),
            'support_phone': self._get_support_phone(),
        })
