# -*- coding: utf-8 -*-
from odoo import api, fields, models


class EasyOrderCategoryImportWizard(models.TransientModel):
    """One-click starting point for setting up Easy Order: rather than
    building the whole category tree by hand from nothing, this copies
    an existing real shop category (name, image, and its products) —
    and everything nested under it — into a brand new easy.order.category
    tree. The two structures stay independent after that; this is a
    one-time copy, not an ongoing sync, so anything renamed or
    re-organized afterward in either place doesn't affect the other.
    """
    _name = 'easy.order.category.import.wizard'
    _description = 'Easy Order - Import Categories from Shop'

    category_ids = fields.Many2many(
        'product.public.category', string='Categories to Import',
        domain=[('parent_id', '=', False)],
        help='Pick which top-level shop categories to copy in. Every '
             'subcategory and product underneath each one comes along '
             'automatically.',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'category_ids' in fields_list:
            top_level = self.env['product.public.category'].search([
                ('parent_id', '=', False),
            ])
            res['category_ids'] = [(6, 0, top_level.ids)]
        return res

    def action_import(self):
        self.ensure_one()
        created = self.env['easy.order.category']
        for real_category in self.category_ids:
            created |= self._import_category(real_category, parent=None)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Imported Categories',
            'res_model': 'easy.order.category',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created.ids)],
        }

    def _import_category(self, real_category, parent):
        templates = self.env['product.template'].sudo().search([
            ('public_categ_ids', 'in', real_category.id),
        ])
        vals = {
            'name': real_category.name,
            'parent_id': parent.id if parent else False,
            'product_tmpl_ids': [(6, 0, templates.ids)],
            # Left blank on purpose: create()'s auto-code-generation (see
            # easy_order_category.py) derives one from the name, only
            # for the top-level ones that actually need it.
        }
        if real_category.image_1920:
            # Our own image field resizes down on write regardless of
            # the source size, so passing the highest-resolution copy
            # available gets the best result.
            vals['image'] = real_category.image_1920
        new_category = self.env['easy.order.category'].create(vals)
        for child in real_category.child_id:
            self._import_category(child, parent=new_category)
        return new_category
