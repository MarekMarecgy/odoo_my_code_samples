# -*- coding: utf-8 -*--
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class DeletedClassName(models.Model):
    _inherit = 'hr.expense'

    currency_rate_id = fields.Many2one('res.currency.rate', string='Currency rate')
    total_amount = fields.Monetary(compute='_compute_amount')
    travel_expense = fields.Boolean(readonly=True)
    partner_id = fields.Many2one('res.partner', string='Vendor')
    product_id = fields.Many2one('product.product',
                                 domain="[('can_be_expensed', '=', True), ('is_advance_payment', '=', False), '|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    advance_payment_rec = fields.Boolean(related='product_id.is_advance_payment')

    @api.depends('quantity', 'unit_amount', 'tax_ids', 'currency_id', 'currency_rate_id')
    def _compute_amount(self):
        for expense in self:
            rate = expense.currency_rate_id.rate if self.env.company.currency_id != expense.currency_id else 1
            expense.untaxed_amount = expense.unit_amount * expense.quantity * rate
            taxes = expense.tax_ids.compute_all(expense.unit_amount * rate, None, expense.quantity,
                                                expense.product_id, expense.employee_id.user_id.partner_id)
            expense.total_amount = taxes.get('total_included')

    @api.onchange('currency_id', 'date')
    def _onchange_currency_id(self):
        for rec in self:
            currency_rate_id = self.env['res.currency.rate'].search(
                [('name', '=', rec.date), ('currency_id', '=', rec.currency_id.id)], limit=1)
            if not currency_rate_id and self.env.company.currency_id != rec.currency_id:
                if not rec.date:
                    raise UserError(_("You have to fill field Date first."))
                raise UserError(_("There is no currency rate for this currency and date."))
            rec.currency_rate_id = currency_rate_id
