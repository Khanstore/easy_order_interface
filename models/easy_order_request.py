# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class EasyOrderRequest(models.Model):
    """A customer's own description of what they want — name, phone,
    address, and a list of items in whatever words they used (often not
    matching any real product name), submitted from the public
    /easy-order/request form.

    This is deliberately NOT a sale.order: nothing here has been matched
    to a real, priced, in-stock product yet, so it shouldn't look like a
    confirmed order anywhere (reporting, invoicing, etc.) until a member
    of staff has actually reviewed it and matched each line to a real
    product via action_create_sale_order below.
    """
    _name = 'easy.order.request'
    _description = 'Easy Order - Customer Order Request'
    _order = 'create_date desc'
    _rec_name = 'customer_name'

    customer_name = fields.Char(string='Customer Name', required=True)
    phone = fields.Char(string='Phone', required=True)
    address = fields.Text(string='Address')
    request_date = fields.Date(
        string='Date', required=True, default=fields.Date.context_today,
        help="When this request came in. Defaults to today, but you can "
             "change it — e.g. if you're logging a phone order a day or "
             "two after the fact.",
    )
    state = fields.Selection([
        ('new', 'New'),
        ('processed', 'Processed'),
    ], default='new', required=True, copy=False)
    sale_order_id = fields.Many2one(
        'sale.order', string='Created Order', readonly=True, copy=False,
    )
    line_ids = fields.One2many(
        'easy.order.request.line', 'request_id', string='Items',
    )

    def action_create_sale_order(self):
        """Staff-triggered: turns this request into a real sale.order,
        once every line has been matched to a real product (see
        easy.order.request.line.product_id). Returns an action so the
        button opens the freshly-created order immediately.
        """
        self.ensure_one()
        if self.state == 'processed':
            raise UserError(_(
                'This request has already been converted to order %s.'
            ) % (self.sale_order_id.name or ''))
        if not self.line_ids:
            raise UserError(_('Add at least one item before creating an order.'))
        unmatched = self.line_ids.filtered(lambda l: not l.product_id)
        if unmatched:
            raise UserError(_(
                'Every line needs a matching real product first — fill in '
                '"Real product" for: %s'
            ) % ', '.join(unmatched.mapped('probable_name')))

        partner = self._find_or_create_partner()
        order = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty,
                # No price_unit here on purpose: leaving it unset lets
                # sale.order.line compute its own price the normal way
                # (pricelist/currency-aware), which is more accurate than
                # anything this screen could capture manually.
            }) for line in self.line_ids],
        })
        self.write({'state': 'processed', 'sale_order_id': order.id})

        return {
            'type': 'ir.actions.act_window',
            'name': _('Sales Order'),
            'res_model': 'sale.order',
            'res_id': order.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _find_or_create_partner(self):
        """Matches an existing customer by phone OR mobile before
        creating a new one, so repeat customers don't end up with a
        duplicate res.partner every time they submit a request —
        checking both fields since a customer's number in the system
        might be filed under either one.
        """
        self.ensure_one()
        partner = self.env['res.partner']
        if self.phone:
            partner = self.env['res.partner'].search([
                '|', ('phone', '=', self.phone), ('mobile', '=', self.phone),
            ], limit=1)
        if partner:
            return partner
        return self.env['res.partner'].create({
            'name': self.customer_name,
            'phone': self.phone,
            'street': self.address,
        })


class EasyOrderRequestLine(models.Model):
    _name = 'easy.order.request.line'
    _description = 'Easy Order - Requested Item'
    _order = 'id'

    request_id = fields.Many2one(
        'easy.order.request', required=True, ondelete='cascade',
    )
    probable_name = fields.Char(
        string='Customer said', required=True,
        help='What the customer typed/said they were looking for — in '
             'their own words, not necessarily a real product name.',
    )
    product_id = fields.Many2one(
        'product.product', string='Real product',
        help='The actual catalog product this line refers to — fill this '
             'in once you\'ve worked out what the customer meant.',
    )
    qty = fields.Float(string='Qty', default=1.0, required=True)

    def action_open_suggest_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Suggested Products',
            'res_model': 'easy.order.request.line.suggest.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_line_id': self.id},
        }
