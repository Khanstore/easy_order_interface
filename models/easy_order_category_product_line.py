# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EasyOrderCategoryProductLine(models.Model):
    _name = 'easy.order.category.product.line'
    _description = 'Easy Order Category Product Selection'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    category_id = fields.Many2one(
        'easy.order.category', required=True, ondelete='cascade', index=True,
        string='Category',
    )
    product_tmpl_id = fields.Many2one(
        'product.template', required=True, ondelete='cascade', index=True,
        string='Product Template',
        help='Choose one product template. If no specific variants are selected, all variants of this template are included.',
    )
    product_variant_ids = fields.Many2many(
        'product.product',
        'easy_order_category_product_line_variant_rel',
        'line_id', 'product_variant_id',
        string='Variants',
        help='Leave empty to include all variants of the selected template. If variants are selected, only those variants are included.',
    )
    product_attribute_ids = fields.Many2many(
        'product.attribute',
        'easy_order_category_product_line_attribute_rel',
        'line_id', 'attribute_id',
        string='Attributes',
        help='Only attributes used by the selected product template are available.',
    )
    product_attribute_value_ids = fields.Many2many(
        'product.attribute.value',
        'easy_order_category_product_line_attr_value_rel',
        'line_id', 'attribute_value_id',
        string='Values',
        help='Only values belonging to the selected template and selected attributes are available. Selecting values filters the included variants.',
    )

    available_product_attribute_ids = fields.Many2many(
        'product.attribute',
        compute='_compute_available_product_attribute_ids',
        string='Available Attributes',
    )
    available_product_attribute_value_ids = fields.Many2many(
        'product.attribute.value',
        compute='_compute_available_product_attribute_value_ids',
        string='Available Values',
    )

    @api.depends('product_tmpl_id')
    def _compute_available_product_attribute_ids(self):
        for line in self:
            line.available_product_attribute_ids = (
                line.product_tmpl_id.attribute_line_ids.attribute_id
                if line.product_tmpl_id else self.env['product.attribute']
            )

    @api.depends('product_tmpl_id', 'product_attribute_ids')
    def _compute_available_product_attribute_value_ids(self):
        for line in self:
            if not line.product_tmpl_id:
                line.available_product_attribute_value_ids = self.env['product.attribute.value']
                continue
            values = line.product_tmpl_id.attribute_line_ids.value_ids
            if line.product_attribute_ids:
                values = values.filtered(
                    lambda value: value.attribute_id in line.product_attribute_ids
                )
            line.available_product_attribute_value_ids = values

    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        for line in self:
            line.product_variant_ids = [(5, 0, 0)]
            line.product_attribute_ids = [(5, 0, 0)]
            line.product_attribute_value_ids = [(5, 0, 0)]

            if not line.product_tmpl_id:
                return {'domain': {
                    'product_variant_ids': [('id', '=', False)],
                    'product_attribute_ids': [('id', '=', False)],
                    'product_attribute_value_ids': [('id', '=', False)],
                }}

            template = line.product_tmpl_id
            attributes = template.attribute_line_ids.attribute_id
            values = template.attribute_line_ids.value_ids
            return {'domain': {
                'product_variant_ids': [('product_tmpl_id', '=', template.id)],
                'product_attribute_ids': [('id', 'in', attributes.ids)],
                # No attribute selected yet: don't offer arbitrary values.
                'product_attribute_value_ids': [('id', '=', False)],
            }}

    @api.onchange('product_attribute_ids')
    def _onchange_product_attribute_ids(self):
        for line in self:
            if not line.product_tmpl_id:
                line.product_attribute_value_ids = [(5, 0, 0)]
                return {'domain': {'product_attribute_value_ids': [('id', '=', False)]}}

            allowed_values = line.product_tmpl_id.attribute_line_ids.value_ids
            if line.product_attribute_ids:
                allowed_values = allowed_values.filtered(
                    lambda value: value.attribute_id in line.product_attribute_ids
                )
                line.product_attribute_value_ids = line.product_attribute_value_ids.filtered(
                    lambda value: value in allowed_values
                )
                return {'domain': {
                    'product_attribute_value_ids': [('id', 'in', allowed_values.ids)],
                }}

            line.product_attribute_value_ids = [(5, 0, 0)]
            return {'domain': {'product_attribute_value_ids': [('id', '=', False)]}}

    @api.constrains('product_tmpl_id', 'product_variant_ids', 'product_attribute_ids', 'product_attribute_value_ids')
    def _check_selections_belong_to_template(self):
        for line in self:
            template = line.product_tmpl_id
            if not template:
                continue
            if line.product_variant_ids.filtered(lambda variant: variant.product_tmpl_id != template):
                raise ValidationError('Selected variants must belong to the selected product template.')
            allowed_attributes = template.attribute_line_ids.attribute_id
            if line.product_attribute_ids - allowed_attributes:
                raise ValidationError('Selected attributes must belong to the selected product template.')
            allowed_values = template.attribute_line_ids.value_ids
            if line.product_attribute_value_ids - allowed_values:
                raise ValidationError('Selected attribute values must belong to the selected product template.')
            if line.product_attribute_value_ids.filtered(
                lambda value: value.attribute_id not in line.product_attribute_ids
            ):
                raise ValidationError('Selected attribute values must belong to one of the selected attributes.')
