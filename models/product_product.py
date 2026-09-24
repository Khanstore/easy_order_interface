# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    # Reverse side of easy.order.category.product_variant_ids. This lets
    # the Easy Order search domain find categories that contain an explicit
    # variant even when its product template itself was not assigned.
    easy_order_category_ids = fields.Many2many(
        'easy.order.category', string='Easy Order Categories',
        relation='easy_order_category_product_variant_rel',
        column1='product_variant_id', column2='category_id',
    )
