# -*- coding: utf-8 -*-
from odoo import api, models


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    @api.model
    def _cositt_invalidate_contracts_for_projects(self, projects):
        projects = projects.filtered(lambda p: p)
        if not projects:
            return
        contracts = self.env['cositt.subscription.contract'].sudo().search([
            ('project_id', 'in', projects.ids),
            ('contract_type', '=', 'hours'),
        ])
        if contracts:
            contracts.invalidate_recordset(['hours_consumed', 'hours_bundle_exhausted'])

    def create(self, vals_list):
        lines = super().create(vals_list)
        projects = lines.mapped('project_id')
        self._cositt_invalidate_contracts_for_projects(projects)
        return lines

    def write(self, vals):
        old_projects = self.mapped('project_id')
        res = super().write(vals)
        projects = old_projects | self.mapped('project_id')
        self._cositt_invalidate_contracts_for_projects(projects)
        return res

    def unlink(self):
        projects = self.mapped('project_id')
        res = super().unlink()
        self.env['account.analytic.line']._cositt_invalidate_contracts_for_projects(projects)
        return res
