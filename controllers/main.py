# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.exceptions import UserError
from odoo.tools.translate import _


class EasyOrderInterface(http.Controller):
    """Controller for the simplified /easy-order browsing experience.

    Cart mutations here deliberately reuse website_sale's own internal
    cart API (website.sale_get_order / sale.order._cart_update) instead
    of writing custom sale.order logic. That keeps this module from
    creating a second, parallel notion of "the current order" that
    could drift out of sync with the standard /shop cart, and it means
    tax/pricelist/stock computation is exactly what the rest of the
    site already relies on.
    """

    def _get_top_level_categories(self):
        return request.env['product.public.category'].sudo().search([
            ('parent_id', '=', False),
        ])

    def _get_cart_quantity(self):
        order = request.website.sale_get_order()
        return order.cart_quantity if order else 0

    @http.route(
        '/easy-order', type='http', auth='public', website=True,
        sitemap=True,
    )
    def easy_order_home(self, **kwargs):
        values = {
            'categories': self._get_top_level_categories(),
            'cart_qty': self._get_cart_quantity(),
        }
        return request.render('easy_order_interface.page_categories', values)

    @http.route(
        '/easy-order/shop/<model("product.public.category"):category>',
        type='http', auth='public', website=True, sitemap=True,
    )
    def easy_order_category(self, category, **kwargs):
        products = request.env['product.template'].sudo().search([
            ('public_categ_ids', 'child_of', category.id),
            ('is_published', '=', True),
            ('sale_ok', '=', True),
        ])
        values = {
            'category': category,
            'products': products,
            'cart_qty': self._get_cart_quantity(),
        }
        return request.render('easy_order_interface.page_products', values)

    @http.route(
        '/easy-order/cart/add', type='json', auth='public', website=True,
        csrf=True,
    )
    def easy_order_add_to_cart(self, product_id, qty=1, **kwargs):
        try:
            product_id = int(product_id)
            qty = float(qty)
        except (TypeError, ValueError):
            return {'error': _("That quantity doesn't look right.")}

        if qty <= 0:
            return {'error': _("Please choose a quantity of at least 1.")}

        product = request.env['product.template'].sudo().browse(product_id)
        if not product.exists() or not product.is_published:
            return {'error': _("Sorry, that item isn't available right now.")}

        order = request.website.sale_get_order(force_create=True)
        try:
            order._cart_update(product_id=product.product_variant_id.id, add_qty=qty)
        except UserError as e:
            # Surfaces things like "out of stock" in plain language rather
            # than a generic failure.
            return {'error': str(e)}

        order_sudo = order.sudo()
        return {
            'cart_qty': order_sudo.cart_quantity,
            'cart_total': order_sudo.amount_total,
        }
