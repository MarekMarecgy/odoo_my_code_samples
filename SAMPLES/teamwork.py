# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

import requests
import base64
import re
import json
from datetime import datetime, date

TEAMWORK_PROJECTS_URL = "/projects/api/v3/projects.json"
TEAMWORK_PEOPLE_ON_PROJECT = "/projects/api/v3/projects/"  # in order to get people on project need to add {projectId}/people.json after '/'
TEAMWORK_COMPANIES = "/projects/api/v3/companies.json"
TEAMWORK_TAGS = "/projects/api/v3/tags.json"
TEAMWORK_PEOPLE = "/projects/api/v3/people.json"
TEAMWORK_TIMESHEETS = "/projects/api/v3/time.json"


class Teamwork(models.Model):
    _name = "teamwork"
    _description = "Teamwork integration"

    name = fields.Char()

    def get_config_parameters(self):
        conf_obj = self.env['ir.config_parameter']
        teamwork_conf_dict = {
            'teamwork_api_key': conf_obj.get_param("DELETED_MODULE_NAME.teamwork_api_key"),
            'teamwork_password': conf_obj.get_param("DELETED_MODULE_NAME.teamwork_password"),
            'teamwork_username': conf_obj.get_param("DELETED_MODULE_NAME.teamwork_username"),
            'teamwork_url': conf_obj.get_param("DELETED_MODULE_NAME.teamwork_url"),
            'selected_method': conf_obj.get_param("DELETED_MODULE_NAME.selected_method"),
        }
        return teamwork_conf_dict

    def check_url(self, url):
        pattern = r'^https://.*?teamwork\.com$'
        if bool(re.match(pattern, url)):
            pass
        else:
            raise ValidationError("Teamwork app url is not correct")

    def get_encoded_credentials(self, arg1, arg2=None):
        if arg2 is None:
            credentials = f"{arg1}"
        else:
            credentials = f"{arg1}:{arg2}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        return encoded_credentials

    def get_authorization_headers(self, configuration_credentials):
        error_msg = "Configuration method is not selected or its fields are not filled"
        auth_method = configuration_credentials.get('selected_method')
        if auth_method == 'api':
            api_key = configuration_credentials.get('teamwork_api_key')
            if not api_key:
                raise ValidationError(error_msg)
            encoded_credentials = self.get_encoded_credentials(api_key)
        elif auth_method == 'uname':
            uname, password = configuration_credentials.get('teamwork_username'), configuration_credentials.get(
                'teamwork_password')
            if uname is False or password is False:
                raise ValidationError(error_msg)
            encoded_credentials = self.get_encoded_credentials(uname, password)
        else:
            raise ValidationError(error_msg)
        headers = {
            "authorization": f"Basic {encoded_credentials}"}
        return headers

    def test_teamwork_connection(self):
        test_url_path = "/projects/api/v3/projects.json"
        configuration_credentials = self.get_config_parameters()
        if configuration_credentials.get('teamwork_url'):
            self.check_url(configuration_credentials.get('teamwork_url'))
            connection_test_url = configuration_credentials.get('teamwork_url') + test_url_path
        else:
            raise UserError("Teamwork app url is not filled")
        headers = self.get_authorization_headers(configuration_credentials)
        response = requests.get(connection_test_url, headers=headers)
        return response

    def get_credentials(self):
        configuration_credentials = self.get_config_parameters()
        teamwork_url = configuration_credentials.get('teamwork_url')
        if teamwork_url:
            self.check_url(teamwork_url)
        else:
            raise UserError("Teamwork app url is not filled")
        headers = self.get_authorization_headers(configuration_credentials)
        return teamwork_url, headers

    def check_companies_diff(self, existing_employee, people, company_obj):
        company = existing_employee.company_id
        teamwork_company = company_obj.search([('teamwork_company_id', '=', people.get('companyId'))])
        if company.id == teamwork_company.id:
            return False
        else:
            return True

    def get_report(self, list_of_diff, list_of_new, list_of_proj):
        message = ''
        if list_of_diff:
            message += '<h3>DIFFERENCES BETWEEN COMPANIES ON EMPLOYEES:</h3> <br></br>'
            for item in list_of_diff:
                message += '-' + item + '<br></br>'
        if list_of_new:
            message += '<h3><br></br>LIST OF NEW EMPLOYEES:</h3> <br></br>'
            for item in list_of_new:
                message += '-' + item + '<br></br>'
        if list_of_proj:
            message += '<h3><br></br>LIST OF PROJECTS THAT DONT EXIST IN ODOO:</h3>'
            for item in list_of_proj:
                message += '-' + item + '<br></br>'
        if message:
            mail_report = self.env.ref('DELETED_MODULE_NAME.mail_report_teamwork')
            report_recipients = self.env['res.users'].search([('report_recipients', '=', True)])
            report_recipients_list = []
            for report_recipient in report_recipients:
                report_recipients_list.append(report_recipient.email_formatted)
            vals = {'body_html': _(
                '<div style="background-color:#ffefef;font-family:Arial,sans-serif;font-size: 14px;"> %s </div>',
                message),
                    'subject': _('Odoo Teamwork Integration Report %s', date.today()),
                    'email_from': self.env.ref('base.user_root').email_formatted,
                    'email_to': report_recipients_list,
                    }
            mail_report.write(vals)
            mail_report.sudo().send_mail(self.id, force_send=True)
        return

    def get_tags(self):
        teamwork_url, headers = self.get_credentials()
        tags_obj = self.env['project.tags']
        tags_url = teamwork_url + TEAMWORK_TAGS
        raw_response_tags = requests.get(tags_url, headers=headers)
        tags_response = json.loads(raw_response_tags.content)
        for tag in tags_response.get('tags'):
            existing_tag = tags_obj.search(
                ['|', ('teamwork_tag_id', '=', tag.get('id')), ('name', '=', tag.get('name'))])
            if existing_tag:
                existing_tag.write({
                    'teamwork_tag_id': tag.get('id')
                })
                continue
            tags_obj.create({
                'teamwork_tag_id': tag.get('id'),
                'name': tag.get('name')
            })
        return tags_obj

    def get_companies(self):
        teamwork_url, headers = self.get_credentials()
        company_obj = self.env['res.company']
        companies_url = teamwork_url + TEAMWORK_COMPANIES
        raw_companies_response = requests.get(companies_url, headers=headers)
        companies_response = json.loads(raw_companies_response.content)
        for company in companies_response.get('companies'):
            existing_company = company_obj.search(['|', ('name', '=', company.get('name')),
                                                   ('teamwork_company_id', '=', company.get('id'))])
            if existing_company:
                existing_company.write({
                    'teamwork_company_id': company.get('id')
                })
                continue
            company_obj.create({
                'teamwork_company_id': company.get('id'),
                'name': company.get('name'),
            })
        return company_obj

    def get_projects(self, tags_obj_arg=None, company_obj_arg=None):
        tags_obj = tags_obj_arg if tags_obj_arg else self.env['project.tags']
        company_obj = company_obj_arg if company_obj_arg else self.env['res.company']
        teamwork_url, headers = self.get_credentials()
        project_obj = self.env['project.project']
        list_of_proj = []
        projects_url = teamwork_url + TEAMWORK_PROJECTS_URL
        raw_response_projects = requests.get(projects_url, headers=headers)
        projects_response = json.loads(raw_response_projects.content)
        for project in projects_response.get('projects'):
            odoo_project = project_obj.search(
                ['|', ('name', '=', project.get('name')), ('teamwork_project_id', '=', project.get('id'))])
            if not odoo_project:
                list_of_proj.append(project.get('name'))
            if odoo_project:
                odoo_project.write({
                    'teamwork_project_id': project.get('id'),
                    'description': project.get('description'),
                    'date_start': project.get('startAt'),
                    'date': project.get('endAt'),
                    'tag_ids': tags_obj.search([('teamwork_tag_id', 'in', project.get('tagIds')),
                                                ('teamwork_tag_id', '!=', False)]).ids or None,
                })
        return project_obj, list_of_proj

    def get_people(self, company_obj_arg=None):
        company_obj = company_obj_arg if company_obj_arg else self.env['res.company']
        teamwork_url, headers = self.get_credentials()
        employees_obj = self.env['hr.employee']
        list_of_diff = []
        list_of_new = []
        people_url = teamwork_url + TEAMWORK_PEOPLE
        raw_response_people = requests.get(people_url, headers=headers)
        people_response = json.loads(raw_response_people.content)
        for people in people_response.get('people'):
            existing_employee = employees_obj.search(
                ['|', ('name', '=', people.get('firstName') + ' ' + people.get('lastName')),
                 ('teamwork_employee_id', '=', people.get('id'))])
            if existing_employee:
                difference = self.check_companies_diff(existing_employee, people, company_obj)
                if difference:
                    list_of_diff.append(existing_employee.name)
                existing_employee.write({
                    'teamwork_employee_id': people.get('id')
                })
                continue
            list_of_new.append(people.get('firstName') + ' ' + people.get('lastName'))
            employees_obj.create({
                'teamwork_employee_id': people.get('id'),
                'name': people.get('firstName') + ' ' + people.get('lastName'),
                'company_id': company_obj.search([('teamwork_company_id', '=', people.get('companyId'))]).id,
                'teamwork_ribbon': True,
            })
        return employees_obj, list_of_diff, list_of_new

    def get_timesheets(self, employees_obj_arg=None, project_obj_arg=None):
        employees_obj = employees_obj_arg if employees_obj_arg else self.env['hr.employee']
        project_obj = project_obj_arg if project_obj_arg else self.env['project.project']
        teamwork_url, headers = self.get_credentials()
        timesheets_obj = self.env['account.analytic.line']
        timesheets_url = teamwork_url + TEAMWORK_TIMESHEETS
        raw_response_timesheets = requests.get(timesheets_url, headers=headers)
        timesheets_response = json.loads(raw_response_timesheets.content)
        for timelog in timesheets_response.get('timelogs'):
            employee = employees_obj.search([('teamwork_employee_id', '=', timelog.get('userId'))])
            project = project_obj.search([('teamwork_project_id', '=', timelog.get('projectId'))])
            if not project:
                continue
            existing_timelog = timesheets_obj.search(
                ['|', ('teamwork_timelog_id', '=', timelog.get('id')),
                 ('date', '=', datetime.strptime(timelog.get('dateCreated'),
                                                 "%Y-%m-%dT%H:%M:%SZ").date()),
                 ('timeLogged', '=', datetime.strptime(timelog.get('timeLogged'), "%Y-%m-%dT%H:%M:%SZ")),
                 ('name', '=', timelog.get('description') or '/'),
                 ('unit_amount', '=', (timelog.get('minutes') / 60)),
                 ('employee_id', '=', employees_obj.search([('teamwork_employee_id', '=', timelog.get('userId'))]).id),
                 ('project_id', '=', project.id)])
            if existing_timelog and not existing_timelog.teamwork_timelog_id or existing_timelog.project_id:
                existing_timelog.write({
                    'teamwork_timelog_id': timelog.get('id'),
                    'project_id': project.id,
                })
                continue
            elif existing_timelog:
                continue
            timesheets_obj.create({
                'teamwork_timelog_id': timelog.get('id'),
                'date': datetime.strptime(timelog.get('dateCreated'), "%Y-%m-%dT%H:%M:%SZ"),
                'employee_id': employee.id,
                'company_id': employee.company_id.id,
                'project_id': project.id,
                'task_id': None,
                'name': timelog.get('description'),
                'unit_amount': (timelog.get('minutes') / 60),
                'timeLogged': datetime.strptime(timelog.get('timeLogged'), "%Y-%m-%dT%H:%M:%SZ"),
            })
        return

    def get_data_from_teamwork(self):
        tags_obj = self.get_tags()
        company_obj = self.get_companies()
        projects_obj, list_of_proj = self.get_projects(tags_obj, company_obj)
        employees_obj, list_of_diff, list_of_new = self.get_people(projects_obj)
        self.get_timesheets(employees_obj, projects_obj)
        self.get_report(list_of_diff, list_of_new, list_of_proj)
        return

    def run_teamwork_cron_manually(self):
        cron = self.env.ref('DELETED_MODULE_NAME.teamwork_update_data_cron')
        cron.sudo().method_direct_trigger()
        return
