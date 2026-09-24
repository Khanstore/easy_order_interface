# -*- coding: utf-8 -*-
import logging
import re

from odoo import http
from odoo.http import request
from odoo.exceptions import UserError
from odoo.osv import expression
from odoo.tools.translate import _
from odoo.tools.misc import formatLang


_logger = logging.getLogger(__name__)

from ..search_matching import (
    _normalize_search_text,
    _tokenize,
    _NORMALIZED_GLOSSARY,
    _LITERAL_GLOSSARY,
    _score_product,
)


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

    def _get_category_variant_domain(self, category):
        """Return the effective product.variant domain for a category.

        Easy Order supports three layers of selection:

        * a selected product template means ALL of that template's variants;
        * a selected product variant means ONLY that variant for its template;
        * selected variant attribute values filter the resulting variants.

        Attribute values behave like useful storefront filters: values from
        the same attribute are OR-ed (Color=Black or Brown), while values
        from different attributes are AND-ed (Color=Black AND Size=L).
        The filter is resolved at read time, so newly-created matching
        variants are included automatically.
        """
        if category.include_subcategory_products:
            subtree_ids = self._get_category_subtree_ids(category)
            categories = request.env['easy.order.category'].sudo().browse(subtree_ids)
        else:
            categories = category

        template_ids = categories.mapped('product_tmpl_ids').ids
        explicit_variant_ids = categories.mapped('product_variant_ids').ids
        attribute_value_ids = categories.mapped('product_attribute_value_ids').ids

        if not template_ids and not explicit_variant_ids:
            return [('id', '=', 0)]

        # A template is expanded to all variants only when that template has
        # no explicit variant assignment in this category scope.
        explicit_variants = request.env['product.product'].sudo().browse(explicit_variant_ids)
        overridden_template_ids = set(
            explicit_variants.mapped('product_tmpl_id').ids
        ) & set(template_ids)
        template_ids = [tid for tid in template_ids if tid not in overridden_template_ids]

        if template_ids and explicit_variant_ids:
            selection_domain = [
                '|',
                ('product_tmpl_id', 'in', template_ids),
                ('id', 'in', explicit_variant_ids),
            ]
        elif template_ids:
            selection_domain = [('product_tmpl_id', 'in', template_ids)]
        else:
            selection_domain = [('id', 'in', explicit_variant_ids)]

        # Attribute filtering is applied AFTER template/variant selection.
        # Group values by their attribute so Color=Black+Brown means either
        # color, while Color=Black+Size=L requires both conditions.
        if attribute_value_ids:
            values = request.env['product.attribute.value'].sudo().browse(attribute_value_ids)
            values_by_attribute = {}
            for value in values:
                values_by_attribute.setdefault(value.attribute_id.id, []).append(value.id)

            for value_ids in values_by_attribute.values():
                selection_domain.append((
                    'product_template_attribute_value_ids.product_attribute_value_id',
                    'in', value_ids,
                ))

        return selection_domain + [
            ('product_tmpl_id.is_published', '=', True),
            ('product_tmpl_id.sale_ok', '=', True),
        ]

    def _get_category_variants(self, category, limit=None, offset=0):
        """Sellable variants selected by a category's template/variant rules."""
        variants = request.env['product.product'].sudo().search(
            self._get_category_variant_domain(category),
            order='product_tmpl_id asc, id asc',
            limit=limit,
            offset=offset,
        )
        # Keep variants from the same template adjacent rather than sorting
        # on the combination suffix first.
        return variants.sorted(key=lambda v: (v.product_tmpl_id.name or '', v.id))

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

    def _get_popular_variants(self, category, limit=6):
        """Return the best-selling variants in this category subtree.

        Popularity is calculated from the full category product set, not
        merely the first paginated page. This keeps the Popular row useful
        after product pagination was introduced.
        """
        variant_domain = self._get_category_variant_domain(category)
        if variant_domain == [('id', '=', 0)]:
            return request.env['product.product']

        groups = request.env['sale.order.line'].sudo().read_group(
            domain=[
                ('product_id', 'in', request.env['product.product'].sudo().search(variant_domain).ids),
                ('order_id.state', 'in', ['sale', 'done']),
            ],
            fields=['product_id', 'product_uom_qty:sum'],
            groupby=['product_id'],
            orderby='product_uom_qty desc',
            limit=limit,
        )
        ordered_ids = [g['product_id'][0] for g in groups if g.get('product_id')]
        return request.env['product.product'].sudo().browse(ordered_ids)

    def _get_buy_again_products(self, limit=8):
        """Products from the logged-in customer's recent completed/confirmed orders.
        Never exposes another customer's order history to the public visitor."""
        user = request.env.user
        if not user or (hasattr(user, '_is_public') and user._is_public()):
            return request.env['product.product']
        partner = user.partner_id
        if not partner:
            return request.env['product.product']
        # Odoo 18 does not allow a dotted relational field such as
        # ``order_id.date_order`` in a sale.order.line SQL ORDER BY.
        # Fetch the customer's orders in date order first, then inspect
        # their lines in that same order.
        orders = request.env['sale.order'].sudo().search([
            ('partner_id', '=', partner.id),
            ('state', 'in', ['sale', 'done']),
        ], order='date_order desc, id desc', limit=100)

        if not orders:
            return request.env['product.product']

        lines = request.env['sale.order.line'].sudo().search([
            ('order_id', 'in', orders.ids),
            ('product_id.product_tmpl_id.is_published', '=', True),
            ('product_id.product_tmpl_id.sale_ok', '=', True),
        ], order='id desc')
        lines_by_order = {}
        for line in lines:
            lines_by_order.setdefault(line.order_id.id, []).append(line)

        seen = set()
        ordered = []
        for order in orders:
            for line in lines_by_order.get(order.id, []):
                product = line.product_id
                if product.id and product.id not in seen:
                    seen.add(product.id)
                    ordered.append(product)
                    if len(ordered) >= limit:
                        break
            if len(ordered) >= limit:
                break
        return request.env['product.product'].sudo().browse([p.id for p in ordered])

    def _product_item(self, variant):
        return {
            'variant_id': variant.id, 'template_id': variant.product_tmpl_id.id,
            'name': variant.display_name,
            'price_formatted': formatLang(request.env, self._get_invoiced_price(variant), currency_obj=variant.currency_id),
            'image_url': '/web/image/product.product/%s/image_128' % variant.id,
            'product_url': getattr(variant.product_tmpl_id, 'website_url', False) or '/shop/product/%s' % variant.product_tmpl_id.id,
            'out_of_stock': self._is_out_of_stock(variant),
        }

    def _get_latest_order(self):
        user = request.env.user
        if not user or (hasattr(user, '_is_public') and user._is_public()):
            return request.env['sale.order']
        return request.env['sale.order'].sudo().search([('partner_id','=',user.partner_id.id),('state','in',['sale','done'])], order='date_order desc, id desc', limit=1)

    def _get_recommended_products(self, category=None, limit=6):
        Product = request.env['product.product'].sudo()
        user = request.env.user
        if not user or (hasattr(user, '_is_public') and user._is_public()):
            return self._get_popular_variants(category, limit=limit) if category else Product
        orders = request.env['sale.order'].sudo().search([('partner_id','=',user.partner_id.id),('state','in',['sale','done'])], order='date_order desc, id desc', limit=20)
        if not orders:
            return self._get_popular_variants(category, limit=limit) if category else Product
        purchased = set(orders.mapped('order_line.product_id').ids)
        lines = request.env['sale.order.line'].sudo().search([('order_id','in',orders.ids),('product_id','not in',list(purchased) or [0]),('product_id.product_tmpl_id.is_published','=',True),('product_id.product_tmpl_id.sale_ok','=',True)])
        scores = {}
        for line in lines:
            scores[line.product_id.id] = scores.get(line.product_id.id, 0) + line.product_uom_qty
        if category:
            allowed = set(self._get_category_variants(category, limit=None).ids)
            scores = {pid: score for pid, score in scores.items() if pid in allowed}
        ranked = sorted(scores, key=lambda pid: (-scores[pid], pid))
        result = Product.browse(ranked[:limit])
        if len(result) < limit and category:
            fallback = self._get_popular_variants(category, limit=limit*2)
            result = Product.browse(list(dict.fromkeys(result.ids + fallback.ids))[:limit])
        return result

    def _build_voice_items(self, text, category_code=None):
        text = (text or '').strip()
        if not text: return []
        nums = {'এক':1,'একটি':1,'একটা':1,'দুই':2,'দুটি':2,'দুটো':2,'তিন':3,'তিনটি':3,'চার':4,'পাঁচ':5,'ছয়':6,'ছয়':6,'সাত':7,'আট':8,'নয়':9,'নয়':9,'দশ':10,'one':1,'a':1,'an':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10}
        parts = re.split(r'\s*(?:,|\band\b|\bও\b|\bএবং\b|\bআর\b)\s*', text, flags=re.I)
        Product = request.env['product.product'].sudo()
        domain=[('product_tmpl_id.is_published','=',True),('product_tmpl_id.sale_ok','=',True)]
        if category_code:
            top=self._get_category_by_code_or_404(category_code)
            if top:
                domain = self._get_category_variant_domain(top)
        catalog=Product.search(domain, limit=1000)
        out=[]
        for part in parts:
            words=part.strip().split(); qty=1
            if words and words[0].lower() in nums: qty=nums[words.pop(0).lower()]
            elif words and words[0].isdigit(): qty=max(1,int(words.pop(0)))
            query=' '.join(words).strip()
            if not query: continue
            groups=[_NORMALIZED_GLOSSARY.get(w,{w}) for w in _tokenize(query)]
            scored=[]
            for product in catalog:
                cats=product.product_tmpl_id.easy_order_category_ids
                score=_score_product(groups,_tokenize(product.display_name),_tokenize(' '.join(cats.mapped('name')+cats.mapped('public_name'))))
                if score: scored.append((score,product))
            scored.sort(key=lambda x:(-x[0],x[1].product_tmpl_id.name or ''))
            if scored: out.append({'qty':qty,**self._product_item(scored[0][1])})
        return out

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
        buy_again = self._get_buy_again_products()
        recommended = self._get_recommended_products()
        values = {
            'top_code': '',
            'categories': self._get_top_level_categories(),
            'buy_again_products': buy_again,
            'buy_again_prices': {v.id: self._get_invoiced_price(v) for v in buy_again},
            'recommended_products': recommended,
            'recommended_prices': {v.id: self._get_invoiced_price(v) for v in recommended},
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
        PAGE_SIZE = 24
        variants = self._get_category_variants(category, limit=PAGE_SIZE)
        all_variant_count = None
        # Count with exactly the same template/variant precedence rules as
        # the product query, so pagination never advertises rows that cannot
        # actually be displayed.
        product_domain = self._get_category_variant_domain(category)
        all_variant_count = request.env['product.product'].sudo().search_count(product_domain)
        product_prices = {
            variant.id: self._get_invoiced_price(variant) for variant in variants
        }
        product_out_of_stock = {
            variant.id: self._is_out_of_stock(variant) for variant in variants
        }
        popular_variants = self._get_popular_variants(category)
        buy_again_products = self._get_buy_again_products() if not category.parent_id else request.env['product.product']
        buy_again_prices = {
            variant.id: self._get_invoiced_price(variant) for variant in buy_again_products
        }
        ancestors = self._get_category_ancestors(category)
        back_url = (
            '/easy-order' if not category.parent_id
            else self._category_url(category.parent_id, top_code)
        )
        recommended_products = self._get_recommended_products(category)
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
            'product_page_size': PAGE_SIZE,
            'product_total': all_variant_count,
            'popular_products': popular_variants,
            'product_prices': product_prices,
            'product_out_of_stock': product_out_of_stock,
            'buy_again_products': buy_again_products,
            'buy_again_prices': buy_again_prices,
            'recommended_products': recommended_products,
            'recommended_prices': {v.id: self._get_invoiced_price(v) for v in recommended_products},
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

    def _build_search_domain(self, query, category_subtree_ids, category=None):
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

        if category:
            base_domain = self._get_category_variant_domain(category)
        else:
            base_domain = [
                ('product_tmpl_id.is_published', '=', True),
                ('product_tmpl_id.sale_ok', '=', True),
                '|',
                ('product_tmpl_id.easy_order_category_ids', 'in', category_subtree_ids),
                ('easy_order_category_ids', 'in', category_subtree_ids),
            ]

        return expression.AND([
            base_domain,
            expression.OR(term_domains),
        ])

    @http.route(
        ['/easy-order/search', '/easy-order/<string:code>/search'], type='json',
        auth='public', website=True,
    )
    def easy_order_search(self, code=None, query='', **kwargs):
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
        if code:
            top = self._get_category_by_code_or_404(code)
            if not top:
                return {'results': []}
            subtree_ids = self._get_category_subtree_ids(top)
        else:
            # Global search for the first /easy-order page.
            subtree_ids = request.env['easy.order.category'].sudo().search([]).ids
            if not subtree_ids:
                return {'results': []}

        query = (query or '').strip()
        if not query:
            return {'results': []}

        # Smart price filter: phrases such as "under 1000", "below ৳1000"
        # and Bengali digits are understood without an external AI service.
        digit_map = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')
        smart_query = query.translate(digit_map)
        price_match = re.search(r'(?:under|below|less than|upto|up to|<=|\bএর নিচে\b|\bকম\b)\s*(?:৳|tk|taka)?\s*([0-9][0-9,]*)', smart_query, flags=re.I)
        max_price = None
        if price_match:
            max_price = float(price_match.group(1).replace(',', ''))
            query = (smart_query[:price_match.start()] + smart_query[price_match.end():]).strip()
        else:
            query = smart_query

        # Each query word expands to itself plus any known translations/
        # synonyms — e.g. "police" also expands to "পুলিশ" (and vice
        # versa), so either spelling finds the same items.
        query_word_groups = [
            _NORMALIZED_GLOSSARY.get(word, {word})
            for word in _tokenize(query)
        ]
        if not query_word_groups and max_price is None:
            return {'results': []}

        domain = self._build_search_domain(query, subtree_ids, category=top if code else None)
        # Category-scoped search already includes the exact category selection
        # domain above, including template/variant precedence and attribute
        # value filters. Global search remains intentionally broad because a
        # product may be assigned to several unrelated categories.
        # Capped so one very common word (e.g. "book") can't drag this
        # whole section's catalog into the Python scoring stage on its
        # own — 300 is comfortably above what any real search needs,
        # since only the top 40 best-scored results ever get returned
        # anyway.
        variants = request.env['product.product'].sudo().search(domain, limit=300)

        scored = []
        for variant in variants:
            template_categories = variant.product_tmpl_id.easy_order_category_ids.filtered(
                lambda c: c.id in subtree_ids
            )
            variant_categories = variant.easy_order_category_ids.filtered(
                lambda c: c.id in subtree_ids
            )
            categories = template_categories | variant_categories
            # Both fields — a search for "law books" (internal) and one
            # for "books" (the shared display name) should both be able
            # to find the same product.
            categ_names = categories.mapped('name') + categories.mapped('public_name')
            name_tokens = _tokenize(variant.display_name)
            categ_tokens = []
            for categ_name in categ_names:
                categ_tokens.extend(_tokenize(categ_name))
            score = _score_product(query_word_groups, name_tokens, categ_tokens) if query_word_groups else 1
            if score:
                if max_price is not None and self._get_invoiced_price(variant) > max_price:
                    continue
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
                'product_url': getattr(variant.product_tmpl_id, 'website_url', False) or '/shop/product/%s' % variant.product_tmpl_id.id,
                'out_of_stock': self._is_out_of_stock(variant),
            })
        return {'results': results}

    @http.route(
        '/easy-order/<string:code>/products', type='json', auth='public', website=True,
    )
    def easy_order_products_page(self, code, category_id, offset=0, limit=24, **kwargs):
        top = self._get_category_by_code_or_404(code)
        try:
            category = request.env['easy.order.category'].sudo().browse(int(category_id))
            offset = max(0, int(offset))
            limit = min(48, max(1, int(limit)))
        except (TypeError, ValueError):
            return {'products': [], 'next_offset': None}
        if not top or not category.exists() or self._get_top_ancestor(category).id != top.id:
            return {'products': [], 'next_offset': None}
        products = self._get_category_variants(category, limit=limit, offset=offset)
        items = []
        for variant in products:
            items.append({
                'variant_id': variant.id,
                'template_id': variant.product_tmpl_id.id,
                'name': variant.display_name,
                'price_formatted': formatLang(request.env, self._get_invoiced_price(variant), currency_obj=variant.currency_id),
                'image_url': '/web/image/product.product/%s/image_128' % variant.id,
                'product_url': getattr(variant.product_tmpl_id, 'website_url', False) or '/shop/product/%s' % variant.product_tmpl_id.id,
                'out_of_stock': self._is_out_of_stock(variant),
            })
        next_offset = offset + len(items) if len(items) == limit else None
        return {'products': items, 'next_offset': next_offset}

    @http.route('/easy-order/favorites', type='http', auth='public', website=True, sitemap=False)
    def easy_order_favorites_page(self, **kwargs):
        return request.render('easy_order_interface.page_favorites', {
            'cart_qty': self._get_cart_quantity(),
            'support_phone': self._get_support_phone(),
        })

    @http.route(
        '/easy-order/favorites/data', type='json', auth='public', website=True,
    )
    def easy_order_favorites(self, product_ids=None, **kwargs):
        try:
            ids = [int(x) for x in (product_ids or [])][:100]
        except (TypeError, ValueError):
            return {'products': []}
        if not ids:
            return {'products': []}
        products = request.env['product.product'].sudo().search([
            ('id', 'in', ids),
            ('product_tmpl_id.is_published', '=', True),
            ('product_tmpl_id.sale_ok', '=', True),
        ])
        by_id = {p.id: p for p in products}
        items = []
        for pid in ids:
            variant = by_id.get(pid)
            if not variant:
                continue
            items.append({
                'variant_id': variant.id, 'template_id': variant.product_tmpl_id.id,
                'name': variant.display_name,
                'price_formatted': formatLang(request.env, self._get_invoiced_price(variant), currency_obj=variant.currency_id),
                'image_url': '/web/image/product.product/%s/image_128' % variant.id,
                'product_url': getattr(variant.product_tmpl_id, 'website_url', False) or '/shop/product/%s' % variant.product_tmpl_id.id,
                'out_of_stock': self._is_out_of_stock(variant),
            })
        return {'products': items}

    @http.route('/easy-order/reorder', type='json', auth='user', website=True, csrf=True)
    def easy_order_reorder(self, **kwargs):
        order=self._get_latest_order()
        if not order: return {'error': _('কোনো আগের অর্ডার পাওয়া যায়নি।')}
        cart=request.website.sale_get_order(force_create=True); added=0
        for line in order.order_line.filtered(lambda l:l.product_id and l.product_id.product_tmpl_id.is_published and l.product_id.product_tmpl_id.sale_ok):
            try: cart._cart_update(product_id=line.product_id.id, add_qty=line.product_uom_qty); added+=1
            except Exception: _logger.exception('Easy Order reorder failed for product %s', line.product_id.id)
        return {'cart_qty':cart.sudo().cart_quantity,'added_lines':added,'cart_url':'/easy-order/checkout'}

    @http.route('/easy-order/voice/parse', type='json', auth='public', website=True, csrf=True)
    def easy_order_voice_parse(self, text='', category_code=None, **kwargs):
        return {'items': self._build_voice_items(text, category_code=category_code)}

    @http.route('/easy-order/favorites/sync', type='json', auth='user', website=True, csrf=True)
    def easy_order_favorites_sync(self, product_ids=None, **kwargs):
        try: ids=list(dict.fromkeys(int(x) for x in (product_ids or [])))[:100]
        except (TypeError,ValueError): ids=[]
        products=request.env['product.product'].sudo().search([('id','in',ids),('product_tmpl_id.is_published','=',True),('product_tmpl_id.sale_ok','=',True)])
        Favorite=request.env['easy.order.favorite'].sudo(); partner=request.env.user.partner_id
        for product in products: Favorite.add_for_partner(partner,product)
        return {'product_ids': Favorite.search([('partner_id','=',partner.id)]).mapped('product_id').ids[:200]}

    @http.route('/easy-order/favorites/remove', type='json', auth='user', website=True, csrf=True)
    def easy_order_favorite_remove(self, product_id, **kwargs):
        try: product_id=int(product_id)
        except (TypeError,ValueError): return {'ok':False}
        request.env['easy.order.favorite'].sudo().search([('partner_id','=',request.env.user.partner_id.id),('product_id','=',product_id)]).unlink()
        return {'ok':True}

    @http.route('/easy-order/checkout', type='http', auth='public', website=True, sitemap=False)
    def easy_order_checkout(self, **kwargs):
        order=request.website.sale_get_order()
        if not order or not order.order_line: return request.redirect('/easy-order')
        return request.render('easy_order_interface.page_checkout', {'order':order.sudo(),'cart_qty':order.cart_quantity,'support_phone':self._get_support_phone()})

    @http.route('/easy-order/orders', type='http', auth='user', website=True, sitemap=False)
    def easy_order_orders(self, **kwargs):
        orders=request.env['sale.order'].sudo().search([('partner_id','=',request.env.user.partner_id.id),('state','in',['sale','done'])],order='date_order desc,id desc',limit=30)
        order_status = {}
        for order in orders:
            pickings = order.picking_ids
            processing = any(p.state in ['assigned', 'done'] for p in pickings) if pickings else False
            delivered = bool(pickings) and all(p.state == 'done' for p in pickings)
            order_status[order.id] = {'processing': processing, 'delivered': delivered}
        return request.render('easy_order_interface.page_orders', {'orders':orders,'order_status':order_status,'cart_qty':self._get_cart_quantity(),'support_phone':self._get_support_phone()})

    @http.route('/easy-order/manifest.json', type='http', auth='public', website=True, sitemap=False)
    def easy_order_manifest(self, **kwargs):
        return request.make_response('{"name":"Easy Order","short_name":"Easy Order","start_url":"/easy-order","display":"standalone","background_color":"#ffffff","theme_color":"#24513f","description":"Simple ordering interface"}',headers=[('Content-Type','application/manifest+json')])

    @http.route('/easy-order/service-worker.js', type='http', auth='public', website=True, sitemap=False)
    def easy_order_service_worker(self, **kwargs):
        js="const CACHE='easy-order-v1';self.addEventListener('install',e=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));});"
        return request.make_response(js,headers=[('Content-Type','application/javascript'),('Service-Worker-Allowed','/easy-order')])

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
        if (
            not product.exists()
            or not product.active
            or not product.is_published
            or not product.sale_ok
        ):
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
            _logger.exception("Easy Order cart update failed for product %s", variant.id)
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
                qty = 0
            if qty <= 0:
                continue
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
