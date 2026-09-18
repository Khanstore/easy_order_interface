# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.osv import expression

from ..search_matching import (
    _LITERAL_GLOSSARY,
    _NORMALIZED_GLOSSARY,
    _normalize_search_text,
    _score_product,
    _tokenize,
)


class EasyOrderRequestLineSuggestWizard(models.TransientModel):
    """Runs a request line's free-text "customer said" description
    through the SAME fuzzy/typo/translation matching engine that powers
    the public /easy-order search box (see search_matching.py) — but
    against the WHOLE real catalog, not just whatever's been assigned
    into Easy Order categories, since staff need to match to any real
    product regardless of whether it's been organized into Easy Order
    yet.

    Opened via the "Suggest" button on easy.order.request.line (see
    action_open_suggest_wizard there); picking one and confirming writes
    straight back onto that line's product_id.
    """
    _name = 'easy.order.request.line.suggest.wizard'
    _description = 'Easy Order - Suggested Products'

    line_id = fields.Many2one(
        'easy.order.request.line', required=True, ondelete='cascade',
    )
    probable_name = fields.Char(related='line_id.probable_name', readonly=True)
    suggestion_ids = fields.Many2many(
        'product.template', string='Suggestions',
        help='The best matches found for what the customer said. If '
             "none of these look right, leave this blank and search "
             "for the real product directly on the line instead.",
    )
    selected_product_tmpl_id = fields.Many2one(
        'product.template', string='Use this product',
        domain="[('id', 'in', suggestion_ids)]",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        line_id = res.get('line_id') or self.env.context.get('default_line_id')
        if line_id and 'suggestion_ids' in fields_list:
            line = self.env['easy.order.request.line'].browse(line_id)
            matches = self._find_matching_templates(line.probable_name)
            res['suggestion_ids'] = [(6, 0, matches.ids)]
            if len(matches) == 1:
                # Only one plausible match — pre-select it so confirming
                # is a single click instead of picking from a list of one.
                res['selected_product_tmpl_id'] = matches.id
        return res

    def _find_matching_templates(self, text, limit=5):
        """Same scoring approach as the public search (see
        controllers/main.py: easy_order_search) but scoped to every
        saleable, published product in the whole catalog rather than one
        Easy Order section — a "Suggest" click needs to find the real
        product wherever it lives, including ones never assigned to any
        Easy Order category yet.

        Prefiltered with the same cheap SQL ilike net the public search
        uses before doing the more expensive Python scoring — a single
        button click is far more forgiving than a live per-keystroke
        search, but scanning a genuinely large catalog in pure Python on
        every click would still be needlessly slow.
        """
        query_word_groups = [
            _NORMALIZED_GLOSSARY.get(word, {word})
            for word in _tokenize(text)
        ]
        if not query_word_groups:
            return self.env['product.template']

        raw_words = [w for w in re.split(r'\s+', (text or '').strip()) if w]
        terms = set()
        for word in raw_words:
            terms.add(word)
            terms |= _LITERAL_GLOSSARY.get(_normalize_search_text(word), set())
        term_domain = expression.OR([[('name', 'ilike', term)] for term in terms])
        domain = expression.AND([
            [('sale_ok', '=', True), ('active', '=', True)],
            term_domain,
        ])

        templates = self.env['product.template'].sudo().search(domain, limit=300)
        scored = []
        for template in templates:
            name_tokens = _tokenize(template.name)
            score = _score_product(query_word_groups, name_tokens, [])
            if score:
                scored.append((score, template))
        scored.sort(key=lambda pair: (-pair[0], pair[1].name or ''))
        top = [tmpl for _score, tmpl in scored[:limit]]
        return self.env['product.template'].browse([t.id for t in top])

    def action_use_suggestion(self):
        self.ensure_one()
        if not self.selected_product_tmpl_id:
            raise UserError('Pick a product first, or close this without choosing one.')
        variant = self.selected_product_tmpl_id.product_variant_id
        if not variant:
            raise UserError(
                'That product has no orderable variant, so it can\'t be '
                'used here.'
            )
        self.line_id.product_id = variant.id
        return {'type': 'ir.actions.act_window_close'}
