# -*- coding: utf-8 -*--
from odoo import fields, models, _


class ResConfigSettings(models.TransientModel):
	_inherit = 'res.config.settings'

	teamwork_api_key = fields.Char(string='Teamwork API Key',
	                               config_parameter="DELETED_MODULE_NAME.teamwork_api_key")
	teamwork_password = fields.Char(string='Teamwork Password',
	                                config_parameter="DELETED_MODULE_NAME.teamwork_password")
	teamwork_username = fields.Char(string='Teamwork Username',
	                                config_parameter="DELETED_MODULE_NAME.teamwork_username")
	teamwork_url = fields.Char(string='Teamwork Url',
	                           config_parameter="DELETED_MODULE_NAME.teamwork_url")
	selected_method = fields.Selection([('api', 'API Key'), ('uname', 'Username')],
	                                 config_parameter="DELETED_MODULE_NAME.selected_method")

	def test_teamwork_connection(self):
		response = self.env["teamwork"].test_teamwork_connection()
		if response.status_code == 200:
			return {
				'type': 'ir.actions.client',
				'tag': 'display_notification',
				'params': {
					'type': 'success',
					'sticky': True,
					'message': _("Connection Works"),
				}
			}
		else:
			return {
				'type': 'ir.actions.client',
				'tag': 'display_notification',
				'params': {
					'type': 'danger',
					'sticky': True,
					'message': _("Connection Fails"),
				}
			}
