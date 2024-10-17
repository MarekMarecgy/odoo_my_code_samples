# -*- coding: utf-8 -*--
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class AdvancePaymentEmployee(models.Model):
    _name = 'advance.payment.employee'

    employee_id = fields.Many2one('hr.employee')
    company_currency_id = fields.Many2one('res.currency', string='Currency',
                                          default=lambda self: self.env.company.currency_id, readonly=True)
    amount = fields.Monetary(string='Amount', required=True, currency_field='company_currency_id')
    collection_date = fields.Date(string='Collection Date', required=True)
    settled = fields.Boolean()
    notes = fields.Text()

    def write_on_expense(self, expense_record, current, operator):
        ops = {"+": (lambda x, y: x + y), "-": (lambda x, y: x - y)}
        expense_record.write({
            'unit_amount': ops[operator](expense_record.unit_amount, current)
        })
        return

    @api.model
    def create(self, vals):
        res = super(AdvancePaymentEmployee, self).create(vals)
        expense_obj = self.env['hr.expense']
        expense_record = expense_obj.search([('employee_id', '=', res.employee_id.id),
                                             ('product_id.is_advance_payment', '=', True)], limit=1)
        if not res.settled and not expense_record:
            advance_payment_record = self.env['product.product'].search([('is_advance_payment', '=', True)])
            hr_expense_record_vals = ({
                'name': advance_payment_record.name,
                'product_id': advance_payment_record.id,
                'currency_id': res.company_currency_id.id,
                'employee_id': res.employee_id.id,
                'unit_amount': -abs(res.amount),
                'quantity': 1,
                'date': res.collection_date,
                'state': 'draft',
                'company_id': res.employee_id.company_id.id,
            })
            expense_obj.create(hr_expense_record_vals)
        elif not res.settled and expense_record:
            self.write_on_expense(expense_record, res.amount, operator='-')
        elif res.settled and expense_record:
            self.write_on_expense(expense_record, res.amount, operator='+')
        return res

    def write(self, vals):
        res = super(AdvancePaymentEmployee, self).write(vals)
        not_settled_lines = self.employee_id.advance_payment_id.filtered(lambda line: line.settled == False)
        not_settled_amount = sum(line.amount for line in not_settled_lines)
        expense_record = self.env['hr.expense'].search([('employee_id', '=', self.employee_id.id),
                                                        ('product_id.is_advance_payment', '=', True)], limit=1)
        if not_settled_amount != 0:
            expense_record.write({
                'unit_amount': -abs(not_settled_amount)
            })
        elif not_settled_amount == 0:
            expense_record.unlink()
        return res

    def unlink(self):
        for record in self:
            if record.settled:
                raise UserError(_("Advance Payment is settled and it can't be deleted"))
        return super(AdvancePaymentEmployee, self).unlink()
