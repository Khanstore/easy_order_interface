# -*- coding: utf-8 -*-
{
    'name': "Easy Order Interface",
    'summary': "Simplified, high-accessibility browse & add-to-cart front page for Khan Store.",
    'description': """
Easy Order Interface
=====================
A custom-controlled entry point (/easy-order) for browsing categories
and products with the "Easy Order" accessibility design, built on top
of website_sale's own cart engine rather than a parallel one.

Architecture notes
-------------------
* Adding a product to cart calls website_sale's own internal cart API
  (`website.sale_get_order` + `sale.order._cart_update`) — the same
  calls Odoo's native /shop page uses. This means correct tax,
  pricelist, and stock handling come for free, and there is only ONE
  sale.order per session, not a parallel order system to keep in sync.
* Checkout itself (address, delivery method, payment) deliberately
  stays on Odoo's standard /shop/cart -> /shop/checkout ->
  /shop/payment flow rather than being reimplemented here, to avoid
  duplicating security-sensitive logic for no real benefit.
* This module is fully self-contained: its own colour/font design
  tokens and a self-hosted copy of Atkinson Hyperlegible (chosen for
  low-vision legibility) live in its own static/ folder — it no
  longer depends on khan_easy_order.
* This module's own CSS/JS load via web.assets_frontend. The frontend
  JavaScript is self-contained (native fetch + a tiny public-widget
  compatibility layer), so it does not require optional Odoo JS modules
  to be present in a particular frontend asset graph. Every style/widget
  is scoped to .eo_* selectors that only exist on this module's pages.
* "Can't find it? Tell us" (/easy-order/request) is a free-text intake
  form for anyone who'd rather describe what they want in their own
  words than browse/search the catalog — e.g. "the book about the
  police officer's life" rather than its real title. Submissions are
  stored as easy.order.request records, NOT sale orders: nothing is
  matched to a real, priced product yet. Staff review them under
  Sales > Easy Order > Requests, fill in the real matching product for
  each line, and click Create Order, which creates and opens a real
  sale.order.
* Browsing structure: /easy-order (a directory of TOP-LEVEL
  easy.order.category tiles — e.g. পুলিশ) -> /easy-order/<code> (that
  top-level category's own subcategories + products) ->
  /easy-order/<code>/shop/<subcategory> (deeper subcategories +
  products, recursively). There's no separate "group" model — a
  top-level category (no Parent Category set) plays that role itself:
  its Code becomes its web address, and everything nested under it
  forms one self-contained section with its own scoped search.
  easy.order.category is a FULLY SEPARATE structure from the real
  shop's product.public.category — deliberately, so Easy Order can be
  organized however makes sense for that audience (merged, split,
  reordered) without being constrained by or interfering with the real
  storefront's navigation. Staff manage it under Sales > Easy Order >
  Categories.
""",
    'version': '18.0.4.5.0',
    'category': 'Website/Website',
    'author': 'SM Ashraf',
    'support': 'shumontor@gmail.com',
    'license': 'LGPL-3',
    'depends': [
        'website_sale',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/easy.order.category.csv',
        'views/templates.xml',
        'views/easy_order_request_views.xml',
        'views/easy_order_category_views.xml',
        'views/easy_order_category_import_wizard_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            # Frontend assets are deliberately self-contained so this
            # module cannot fail because a theme/custom bundle omitted
            # an Odoo legacy frontend module. Styles and widgets are
            # scoped to the Easy Order page.
            #
            # Colour/font tokens + self-hosted @font-face rules must
            # load before easy_order_interface.scss, which uses them.
            'easy_order_interface/static/src/scss/easy_order_tokens.scss',
            'easy_order_interface/static/src/scss/easy_order_interface.scss',
            'easy_order_interface/static/src/js/easy_order_interface.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
