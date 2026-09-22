# -*- coding: utf-8 -*-
from odoo import api, fields, models

class EasyOrderFavorite(models.Model):
    _name = "easy.order.favorite"
    _description = "Easy Order - Customer Favorite"
    _order = "create_date desc, id desc"
    partner_id = fields.Many2one("res.partner", required=True, index=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True, index=True, ondelete="cascade")
    _sql_constraints = [("partner_product_unique", "unique(partner_id, product_id)", "A customer can favorite a product only once.")]
    @api.model
    def add_for_partner(self, partner, product):
        rec = self.search([("partner_id","=",partner.id),("product_id","=",product.id)], limit=1)
        return rec or self.create({"partner_id":partner.id,"product_id":product.id})
