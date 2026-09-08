# -*- coding: utf-8 -*-
import re
import unicodedata

from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Reserved so a top-level category's code can never collide with one of
# this module's own literal URL segments directly under /easy-order/ —
# see the routes in controllers/main.py. "request" is the only real
# collision today (/easy-order/request), but a couple of others are
# blocked defensively in case future routes ever add a literal segment
# at this same depth.
_RESERVED_CODES = {'request', 'search', 'shop'}


def _slugify(text):
    """Best-effort URL-safe slug from a name — used to auto-generate a
    top-level category's code so staff don't have to think one up by
    hand. Only handles Latin-script input meaningfully: Bengali (or any
    other non-Latin) text gets stripped out entirely by the ASCII
    encode/decode step, since a "phonetic" transliteration would be a
    guess dressed up as a real feature. Falling back to "category" (see
    _generate_unique_code below) when that happens is honest about the
    limitation rather than producing a nonsense slug.
    """
    if not text:
        return ''
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    text = text.lower()
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')


class EasyOrderCategory(models.Model):
    """Easy Order's own category tree — deliberately NOT the same model as
    the real shop's product.public.category. This lets Easy Order be
    organized however makes sense for that audience (merged, split,
    renamed, reordered) without touching or being constrained by the
    real storefront's navigation, and without every real category
    automatically becoming visible here.

    There's no separate "group" model — a TOP-LEVEL category (no
    parent_id) plays that role itself: its `code` becomes the URL
    (/easy-order/<code>), and it — along with every category nested
    under it — forms one self-contained "section" of the site (its own
    scoped search, its own little storefront). A category only shows up
    on the public site once it's nested (directly or indirectly) under
    some top-level category — there's no separate publish flag to
    forget to tick.
    """
    _name = 'easy.order.category'
    _description = 'Easy Order - Category'
    _order = 'sequence, name'

    name = fields.Char(
        required=True,
        help='Internal name — this is what YOU use to tell categories '
             'apart in the backend (e.g. "Law Books" vs "Medical '
             'Books"). Customers never see this. What they see is '
             '"Display Name" below.',
    )
    public_name = fields.Char(
        string='Display Name',
        help='What customers actually see on the website. Leave blank '
             'to just show the Internal Name above instead. Handy when '
             'two different categories should look the same to '
             'customers but hold different products — e.g. an '
             'internal "Law Books" and "Medical Books" can both '
             'display simply as "Books" under their own top-level '
             'section.',
    )
    code = fields.Char(
        help='URL address for a TOP-LEVEL category (one with no Parent '
             'Category set below) — e.g. code "police" means '
             '/easy-order/police. Leave this blank and one is '
             'generated from the name automatically; only fill it in '
             "if you want a specific address. Subcategories don't use "
             'this at all.',
    )
    image = fields.Image(string='Image', max_width=1024, max_height=1024)
    sequence = fields.Integer(
        default=10,
        help='Controls the display order among sibling categories '
             '(lower numbers first) — both the top-level tiles on the '
             '/easy-order home page and the subcategory tiles within a '
             'category. Drag rows in the list view to reorder them, or '
             'type a number here directly.',
    )
    parent_id = fields.Many2one(
        'easy.order.category', string='Parent Category', ondelete='cascade',
    )
    child_ids = fields.One2many(
        'easy.order.category', 'parent_id', string='Subcategories',
    )
    category_path = fields.Char(
        string='Full Path', compute='_compute_category_path', store=True,
        help='Where this category sits in the tree, e.g. '
             '"police/book/handbook" — read-only, just here so you can '
             'tell at a glance where a deeply-nested category lives '
             'without clicking through its parents one by one.',
    )
    include_subcategory_products = fields.Boolean(
        string='Show products from subcategories too',
        default=False,
        help='By default, this category\'s page only shows products '
             'assigned directly to IT — not ones assigned to its '
             'subcategories. Turn this on to also pull in every '
             'product from every subcategory underneath this one '
             '(and their subcategories, and so on). Example: if '
             '"Guides" is nested under police/books and has its own '
             'products, checking this on "Books" (or on "Police") '
             'makes those same products also show up there.',
    )
    product_tmpl_ids = fields.Many2many(
        'product.template', string='Products',
        relation='easy_order_category_product_rel',
        column1='category_id', column2='product_tmpl_id',
        help='The real catalog products that show up when a customer '
             'browses this category. A product can be assigned to more '
             'than one Easy Order category.',
    )

    @api.depends('name', 'parent_id.category_path')
    def _compute_category_path(self):
        for category in self:
            if category.parent_id:
                category.category_path = '%s/%s' % (
                    category.parent_id.category_path, category.name,
                )
            else:
                category.category_path = category.name

    @api.depends('category_path', 'name')
    def _compute_display_name(self):
        # Overrides the default (which would just show the bare Internal
        # Name) so that anywhere this category shows up in a dropdown —
        # most importantly the Parent Category picker — three different
        # "Book" categories nested under three different top-level
        # sections read as "police/book", "students/book", "her/book"
        # instead of all looking identical and unpickable.
        for category in self:
            category.display_name = category.category_path or category.name

    def _search_display_name(self, operator, value):
        # Odoo 18 searches Many2one autocomplete ("type to search") through
        # this hook rather than matching the (non-stored-by-default)
        # display_name column directly. Without this override, typing
        # "police" into the Parent Category field would find nothing —
        # the stored, searchable column is still `name` ("Book"), not the
        # computed display label ("police/book") shown in the dropdown.
        return ['|', ('name', operator, value), ('category_path', operator, value)]

    _sql_constraints = [
        ('code_unique', 'unique(code)',
         'This code is already used by another Easy Order category — '
         "each top-level category's code has to be unique since it's "
         'what identifies it in the URL.'),
    ]

    def _generate_unique_code(self, base_text):
        """A URL-safe, unique code derived from `base_text` (normally the
        category's own name) — appends "-2", "-3", etc. if the plain
        slug is already taken, and avoids ever landing on one of this
        module's reserved words (see _RESERVED_CODES).
        """
        base = _slugify(base_text) or 'category'
        if base in _RESERVED_CODES:
            base = '%s-category' % base
        code = base
        suffix = 2
        Category = self.env['easy.order.category']
        while Category.search_count([('code', '=', code)]):
            code = '%s-%d' % (base, suffix)
            suffix += 1
        return code

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('parent_id') and not vals.get('code'):
                vals['code'] = self._generate_unique_code(
                    vals.get('public_name') or vals.get('name') or ''
                )
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        # Covers cases the create() override above can't: a Parent
        # Category being cleared (making a former subcategory top-level
        # for the first time), or a record that somehow ended up with an
        # empty code some other way. Reassigning `category.code` here —
        # rather than folding it into the `vals` already being written —
        # re-enters write() with just that one field for that one
        # record, which naturally terminates: by then code is set, so
        # the condition below is false and nothing recurses further.
        for category in self:
            if not category.parent_id and not category.code:
                category.code = self._generate_unique_code(
                    category.public_name or category.name
                )
        return res

    @api.constrains('code', 'parent_id')
    def _check_code(self):
        for category in self:
            if category.parent_id:
                # Subcategories don't use their code for anything, so an
                # accidentally-filled-in one isn't worth blocking on —
                # just skip validation rather than force it blank.
                continue
            if not category.code:
                # Shouldn't normally happen — create()/write() above
                # auto-generate one — but kept as a safety net for any
                # path that bypasses them (e.g. a raw SQL import).
                raise ValidationError(
                    'The top-level category "%s" needs a code — it '
                    "becomes that category's web address (e.g. "
                    '"police" means /easy-order/police).' % category.name
                )
            if not re.fullmatch(r'[a-z0-9-]+', category.code):
                raise ValidationError(
                    'The code "%s" isn\'t valid — use only lowercase '
                    'letters, numbers, and hyphens (e.g. "police", '
                    '"eid-collection"), since this becomes part of a web '
                    'address.' % category.code
                )
            if category.code in _RESERVED_CODES:
                raise ValidationError(
                    'The code "%s" is reserved for this module\'s own '
                    'use and can\'t be used for a category — please '
                    'pick a different one.' % category.code
                )
