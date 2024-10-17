# -*- coding: utf-8 -*--
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import xlrd
import itertools
from odoo.tools import config, DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT, DEFAULT_SERVER_TIME_FORMAT, \
	str2bool
from datetime import datetime, time

from odoo import models, fields, api, _
from odoo.exceptions import Warning, UserError
import base64
import os
import ast


class PayrollImport(models.TransientModel):
	_name = 'payroll.import'

	data = fields.Binary('File to import', required=True)
	filename = fields.Char('File Name', required=True)

	def read_xls_book(self, book, sheet_name, range_from=0):
		''' Method copied from base import module
		@param range_from: index of row from which data to import start (names of columns)'''
		sheet = book.sheet_by_name(sheet_name)
		# emulate Sheet.get_rows for pre-0.9.4
		for rowx, row in enumerate(map(sheet.row, range(range_from, sheet.nrows)), 1):
			values = []
			for colx, cell in enumerate(row, 1):
				if cell.ctype is xlrd.XL_CELL_NUMBER:
					is_float = cell.value % 1 != 0.0
					values.append(
						str(cell.value)
						if is_float
						else str(int(cell.value))
					)
				elif cell.ctype is xlrd.XL_CELL_DATE:
					is_time = False
					is_datetime = cell.value % 1 != 0.0
					res = xlrd.xldate.xldate_as_tuple(cell.value, book.datemode)
					if res[0:3] == (0, 0, 0):
						is_time = True
						dt = time(*res[3:])
					else:
						dt = datetime(*xlrd.xldate.xldate_as_tuple(cell.value, book.datemode))
					if is_time:
						values.append(dt.strftime(DEFAULT_SERVER_TIME_FORMAT))
					elif is_datetime:
						values.append(dt.strftime(DEFAULT_SERVER_DATETIME_FORMAT))
					else:
						values.append(dt.strftime(DEFAULT_SERVER_DATE_FORMAT))
				elif cell.ctype is xlrd.XL_CELL_BOOLEAN:
					values.append(u'True' if cell.value else u'False')
				elif cell.ctype is xlrd.XL_CELL_ERROR:
					raise ValueError(
						_("Invalid cell value at row %(row)s, column %(col)s: %(cell_value)s") % {
							'row': rowx,
							'col': colx,
							'cell_value': xlrd.error_text_from_code.get(cell.value,
							                                            _("unknown error code %s", cell.value))
						}
					)
				else:
					values.append(cell.value)
			if any(x for x in values if x.strip()):
				filtered_values = list(filter(lambda x: x not in ('', 'False'), values))
				if filtered_values:
					yield values

	def search_employee(self, column_name, headers, datas, field_name):
		index = headers.index(column_name)
		value = datas[index]
		employee = self.env['hr.employee'].search([(field_name, '=', value)])
		return employee, value

	def check_employee_and_email(self, sheet, headers, datas, employee_error_rows, create_employee=False,
	                             error_sheet_name=False):
		configuration_obj = self.env['payroll.import.configuration']
		error_sheet_name = error_sheet_name or sheet

		empl_id_conf_rec = configuration_obj.search(
			[('sheet', '=', sheet), ('related_field.name', '=', 'customer_employee_no')])
		if not empl_id_conf_rec:
			raise UserError('Configuration for column Customer Employee ID not found.')
		employee, empl_code = self.search_employee(empl_id_conf_rec.column_name, headers, datas, 'customer_employee_no')

		if (employee and create_employee) or (not employee and not create_employee):
			employee_error_rows[error_sheet_name] += [empl_code]
			return False, employee_error_rows, empl_code

		work_email_conf_rec = configuration_obj.search(
			[('sheet', '=', sheet), ('related_field.name', '=', 'work_email')])
		if work_email_conf_rec:  # need to check work_email because of constraint
			employee, work_email = self.search_employee(work_email_conf_rec.column_name, headers, datas, 'work_email')
			if employee:
				employee_error_rows[error_sheet_name] += [work_email]
				return False, employee_error_rows, empl_code

		identification_no_conf_rec = configuration_obj.search(
			[('sheet', '=', sheet), ('related_field.name', '=', 'identification_id')])
		if identification_no_conf_rec:  # need to check identification_id because of constraint
			employee, identification_id = self.search_employee(identification_no_conf_rec.column_name, headers, datas,
			                                                   'identification_id')
			if employee:
				employee_error_rows[error_sheet_name] += [identification_id]
				return False, employee_error_rows, empl_code

		return True, employee_error_rows, empl_code

	def map_column_number(self, datas, index):
		map_column = {
			'Column 1': 'column1',
			'Column 2': 'column2',
			'Column 3': 'column3',
			'Column 4': 'column4',
			'Column 5': 'column5',
			'Column 6': 'column6',
		}
		datas[index] = map_column.get(datas[index])
		return datas

	def change_hour_to_float(self, hour):
		hour_list = hour.split(':')
		return int(hour_list[0]) + int(hour_list[1]) / 60.0

	def get_key_by_value(self, selection_string, search_value):
		list_of_tuples = ast.literal_eval(selection_string)
		for key, value in dict(list_of_tuples).items():
			if value == search_value:
				return key
		return None

	def get_message(self, employee_error_rows, create_write_errors, other_errors):
		message = ''
		create_empl_sheet = self.env['payroll.import.sheet.configuration'].search(
			[('create_employee', '=', True), ('parent_id', '=', False)], limit=1)
		if create_empl_sheet.name in employee_error_rows.keys():
			hire_err = employee_error_rows.pop(create_empl_sheet.name)
			if hire_err:
				message += 'For sheet ' + create_empl_sheet.name + ': \nThere are already employees with this id, email or identification no. in the system: ' + ', '.join(
					hire_err) + '\n\n'
		for key, value in employee_error_rows.items():
			if value:
				message += 'For sheet ' + key + ': \nThere are no employee with ids: ' + ', '.join(
					value) + ' in the system\n\n'
		if create_write_errors:
			message += 'Create / update errors for rows: \n' + '\n'.join(create_write_errors) + '\n\n'
		if other_errors:
			message += 'Not found records: ' + ', '.join(other_errors)

		if not message:
			message = 'Import from file completed. All of data imported.'
		return message

	def get_vals_to_create_write(self, datas, headers, configuration_recs, errors):
		bank_account_vals = {}
		dict_keys = configuration_recs.mapped('object.model')
		vals = {dict_key: {} for dict_key in dict_keys}

		for data, header, conf_rec in zip(datas, headers, configuration_recs):
			field_type = conf_rec.related_field.ttype
			if field_type == 'many2one':
				if conf_rec.related_field.name == 'variable_component':
					if data:
						component_vals = {header: [conf_rec.related_component.id, data, 'undefined']}
						if vals[conf_rec.object.model].get('variable_component'):
							vals[conf_rec.object.model]['variable_component'].update(component_vals)
						else:
							vals[conf_rec.object.model].update({'variable_component': component_vals})
				else:
					field_name = 'acc_number' if conf_rec.related_field.name == 'bank_account_id' else 'name'
					related_record = self.env[conf_rec.related_field.relation].search(
						[(field_name, '=', data)], limit=1)

					if not related_record and data:  # if the value is empty (== '') go ahead
						if conf_rec.related_field.name == 'bank_account_id':
							bank_account_vals = ({
								'acc_number': data,
								'acc_type': 'bank',
							})
						else:
							errors += [data]
					else:
						vals[conf_rec.object.model].update({conf_rec.related_field.name: related_record.id})
			elif field_type == 'selection':
				vals[conf_rec.object.model].update(
					{conf_rec.related_field.name: self.get_key_by_value(conf_rec.related_field.selection, data)})
			else:
				if conf_rec.related_field.name == 'additional_currency' and vals['variable.component'].get(
						'variable_component'):
					component_dict = vals['variable.component']['variable_component']
					to_rewrite = [k for k, v in component_dict.items() if 'undefined' in v]
					for component in to_rewrite:
						component_dict[component][component_dict[component].index('undefined')] = data
				else:
					vals[conf_rec.object.model].update(
						{conf_rec.related_field.name: int(data) if field_type == 'integer' else data})
					if field_type == 'boolean' and data == 'True' and '_ac' in conf_rec.related_field.name:
						key_to_rewrite = conf_rec.related_field.name[:-3]
						vals[conf_rec.object.model].update({
							key_to_rewrite + '_in_ac': vals[conf_rec.object.model].get(key_to_rewrite),
							key_to_rewrite: ''})

		return vals, errors, bank_account_vals

	def create_write_records(self, sheet: str, vals: dict, employee_code: str, bank_account_vals: dict,
	                         create_employee: bool, models: list, parent_create_employee: bool) -> list:
		employee_obj = self.env['hr.employee']
		contract_obj = self.env['hr.contract']
		errors = []
		try:
			if 'hr.employee' in models and 'hr.contract' in models and create_employee:  # sheet 'New Hire'
				vals['hr.employee'].update({'parent_id': 1,
				                            'job_id': vals['hr.contract'].get('job_id')})
				employee = employee_obj.create(vals['hr.employee'])
				bank_account_vals.update({'partner_id': employee.user_partner_id.id})
				if bank_account_vals and bank_account_vals.get('acc_number'):
					bank_account = self.env['res.partner.bank'].create(bank_account_vals)
					employee.bank_account_id = bank_account.id

				vals['hr.contract'].update({'employee_id': employee.id,
				                            'name': f'{employee.name} Contract',
				                            'state': 'open'})
				contract_obj.create(vals['hr.contract'])
			elif 'hr.leave' in models:  # sheet 'Absence Report'
				employee_leave = employee_obj.search(
					[('customer_employee_no', '=', vals['hr.leave'].get('customer_employee_no'))])
				leave_type = self.env['hr.leave.type'].browse(vals['hr.leave'].get('holiday_status_id'))

				if leave_type.request_unit == 'hour' and vals['hr.leave'].get('request_hour_from') and vals[
					'hr.leave'].get('request_hour_to'):
					hour_from = self.change_hour_to_float(vals['hr.leave']['request_hour_from'])
					hour_to = self.change_hour_to_float(vals['hr.leave']['request_hour_to'])
					vals['hr.leave'].update({'request_unit_hours': True,
					                         'request_hour_from': hour_from,
					                         'request_hour_to': hour_to,
					                         'date_to': vals['hr.leave'].get('date_from')
					                         })

				date_from_datetime = datetime.combine(
					fields.Date.from_string(vals['hr.leave'].get('date_from')), datetime.min.time())
				date_to_datetime = datetime.combine(
					fields.Date.from_string(vals['hr.leave'].get('date_to')), datetime.max.time())

				vals['hr.leave'].update({'employee_id': employee_leave.id,
				                         'date_from': date_from_datetime,
				                         'request_date_from': date_from_datetime,
				                         'request_date_to': date_to_datetime,
				                         'date_to': date_to_datetime,
				                         })
				leave = self.env['hr.leave'].create(vals['hr.leave'])
				leave._compute_date_from_to()
				leave.action_approve()
			elif 'variable.component' in models and vals['variable.component'].get(
					'variable_component'):  # sheet 'Master Data'
				component_obj = self.env['variable.component']
				employee = employee_obj.search(
					[('customer_employee_no', '=', vals['variable.component'].get('customer_employee_no'))])
				vals['variable.component'].update({'employee_id': employee.id,
				                                   'department_id': employee.department_id.id,
				                                   'source': 'import'})
				component_vals = vals['variable.component'].pop('variable_component')
				for component_id, component_value, additional_currency in component_vals.values():
					domain = [('employee_id', '=', employee.id),
					          ('department_id', '=', employee.department_id.id),
					          ('date_from', '=', vals['variable.component'].get('date_from') or False),
					          ('date_to', '=', vals['variable.component'].get('date_to') or False),
					          ('variable_component', '=', component_id)]
					common_vals_to_create_write = {'value': int(component_value)}
					if additional_currency != 'undefined':
						domain += [('additional_currency', '=', str2bool(additional_currency))]
						common_vals_to_create_write.update({'additional_currency': str2bool(additional_currency)})
					component = component_obj.search(domain)
					if component:
						if int(component_value) == 0:
							component.unlink()
						else:
							component.write(common_vals_to_create_write)
					else:
						vals['variable.component'].update(common_vals_to_create_write)
						vals['variable.component'].update({'variable_component': component_id})

						component_obj.create(vals['variable.component'])
			elif 'hr.employee' in models and 'hr.contract' in models and not create_employee:  # sheet 'Termination' or 'Permanent Data Changes'
				employee = employee_obj.search([('customer_employee_no', '=', employee_code)])
				if parent_create_employee:  # sheet 'Permanent Data Changes'
					to_write_empl_vals = {}
					[to_write_empl_vals.update({key: value}) for key, value in vals['hr.employee'].items()
					 if value not in ('', False, None) and key != 'customer_employee_no']
					if to_write_empl_vals:
						employee_obj.write(to_write_empl_vals)

					to_write_contract_vals = {}
					[to_write_contract_vals.update({key: value}) for key, value in vals['hr.contract'].items()
					 if value not in ('', False, None, 'True',
					                  'False')]  # eg. to_write_contract_vals: {'wage_in_ac': '13000', 'hourly_wage': '120'}
					if to_write_contract_vals:
						# need to get checboxes with information about additional currency
						[to_write_contract_vals.update({key: str2bool(value)}) for key, value in
						 vals['hr.contract'].items()
						 if '_ac' in key and (key.replace('_ac', '') in to_write_contract_vals.keys() or
						                      key.replace('_ac', '_in_ac') in to_write_contract_vals.keys())]
						vals['hr.contract'] = to_write_contract_vals

				if employee.contract_id.state == 'open':
					employee.contract_id.write(vals['hr.contract'])
				else:
					errors += [f'Employee code: {employee_code}, Sheet: {sheet}, Exception: No open contract']


		except Exception as e:
			errors += [f'Employee code: {employee_code}, Sheet: {sheet}, Exception: {e}']

		return errors

	def prepare_sheets(self):

		def _get_file_data(book, sheet_name):
			rows = self.read_xls_book(book, sheet_name, 3)
			headers = next(rows, None)
			preview = list(itertools.islice(rows, 100))
			return headers, preview

		employee_error_rows = {}
		book = xlrd.open_workbook(file_contents=base64.b64decode(self.data) or b'')
		sheets = book.sheet_names()
		sheet_conf_parent = self.env['payroll.import.sheet.configuration'].search(
			[('name', 'in', sheets), ('parent_id', '=', False)])
		sheets_dict = {}
		for parent in sheet_conf_parent:
			change_data_sheets = parent.change_data_sheet.filtered(lambda x: x.name in sheets)
			sorted_change_data_sheets = sorted(list(change_data_sheets), key=lambda x: x.sequence, reverse=True)
			for change_data_sheet in sorted_change_data_sheets:
				headers, preview = _get_file_data(book, change_data_sheet.name)
				if preview:
					sheets_dict.update(
						{parent.name: [headers, preview, change_data_sheet.create_employee, change_data_sheet.name,
						               parent.create_employee]})
					employee_error_rows.update({change_data_sheet.name: []})
					break
			if not sheets_dict.get(parent.name):
				headers, preview = _get_file_data(book, parent.name)
				sheets_dict.update({parent.name: [headers, preview, parent.create_employee, False, False]})
				employee_error_rows.update({parent.name: []})

		return employee_error_rows, sheets_dict

	def action_import(self):
		fileformat = os.path.splitext(self.filename)[-1][1:].lower()
		if fileformat not in ('xls', 'xlsx'):
			raise Warning('Invalid file type %s' % fileformat)

		to_map = self.env['payroll.import.configuration']
		other_errors = []
		create_write_errors = []

		employee_error_rows, sheets_dict = self.prepare_sheets()

		for sheet, data_list in sheets_dict.items():
			headers = data_list[0]
			configuration_recs_list = list(
				map(lambda h: to_map.search([('sheet.name', '=', sheet), ('column_name', '=', h)]) or False, headers))
			# prepare lists - delete values that are not in configuration
			to_delete = [i for i, conf_rec in enumerate(configuration_recs_list) if conf_rec == False]
			to_delete.sort(reverse=True)
			list(map(lambda i: (configuration_recs_list.pop(i), headers.pop(i)), to_delete))
			configuration_recs = to_map.concat(*configuration_recs_list)

			preview = data_list[1]  # lists with data
			create_employee = data_list[2]
			secondary_sheet = data_list[3]  # data_list[3] is the name of sheet from file - if not False we know that
			# have to change data, not create new records, also need it for catching errors
			parent_create_employee = data_list[4]  # need to recognize sheet which update employee and contract records
			for datas in preview:
				list(map(lambda i: datas.pop(i), to_delete))
				# find employee_code (Employee ID) and check if exists
				create_record, employee_error_rows, employee_code = self.check_employee_and_email(sheet, headers, datas,
				                                                                                  employee_error_rows,
				                                                                                  create_employee,
				                                                                                  secondary_sheet)
				if create_record:
					if 'column_number' in configuration_recs.mapped('related_field.name'):
						datas = self.map_column_number(datas, configuration_recs.mapped('related_field.name').index(
							'column_number'))

					vals, other_errors, bank_account_vals = self.get_vals_to_create_write(datas, headers,
					                                                                      configuration_recs,
					                                                                      other_errors)
					if other_errors:
						continue

					create_write_errors += self.create_write_records(secondary_sheet or sheet, vals, employee_code,
					                                                 bank_account_vals, create_employee,
					                                                 configuration_recs.mapped('object.model'),
					                                                 parent_create_employee)
		message = self.get_message(employee_error_rows, create_write_errors, other_errors)
		display_message = self.env['display.message'].create({'message': message})

		return {
			'type': 'ir.actions.act_window',
			'name': 'Import Summary',
			'view_mode': 'form',
			'res_model': 'display.message',
			'target': 'new',
			'res_id': display_message.id,
			'views': [[self.env.ref('DELETED_MODULE_NAME.view_display_message_form').id, 'form']],
		}
