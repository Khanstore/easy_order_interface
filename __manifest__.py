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
  /shop/payment flow rather than being reimplemented here. That flow
  already carries the accessibility styling from khan_easy_order, and
  reimplementing payment/address handling from scratch would duplicate
  a lot of security-sensitive logic for no real benefit.
* This module depends on khan_easy_order so it reuses that module's
  design tokens (colours) and self-hosted fonts instead of shipping a
  second copy of the same assets.
* This module's own CSS/JS load in a DEDICATED bundle
  (easy_order_interface.assets_easy_order_page), included only inside
  this module's own templates via <t t-call-assets=.../> — NOT in the
  shared web.assets_frontend bundle. That means /easy-order is the only
  page that loads them; every other page on the site (including /shop
  and checkout) is completely unaffected by this module.
""",
    'version': '18.0.1.0.1',
    'category': 'Website/Website',
    'author': 'Khan Store',
    'license': 'LGPL-3',
    'depends': [
        'website_sale',
        'khan_easy_order',
    ],
    'data': [
        'views/templates.xml',
    ],
    'assets': {
        'easy_order_interface.assets_easy_order_page': [
            # Only the design-token variables from khan_easy_order —
            # not its site-wide override rules — so this page can use
            # $eo-forest / $eo-gold / etc. without pulling in anything
            # that touches other pages.
            'khan_easy_order/static/src/scss/easy_order_variables.scss',
            'easy_order_interface/static/src/scss/easy_order_interface.scss',
            'easy_order_interface/static/src/js/easy_order_interface.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
