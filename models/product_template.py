# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # The reverse side of easy.order.category.product_tmpl_ids — same
    # relation table, columns swapped. Declared explicitly (Odoo doesn't
    # auto-create a reverse accessor for a Many2many) so controllers can
    # traverse from a product to its Easy Order categories, e.g. to scope
    # search to only the current top-level section's assigned products.
    easy_order_category_ids = fields.Many2many(
        'easy.order.category', string='Easy Order Categories',
        relation='easy_order_category_product_rel',
        column1='product_tmpl_id', column2='category_id',
    )
