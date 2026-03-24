# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    cositt_recurring_contract = fields.Boolean(
        string='Contrato recurrente (Cositt)',
        default=False,
        help='Si está marcado, las líneas de pedido con este producto pueden generar contratos recurrentes al confirmar el presupuesto.',
    )
    cositt_contract_sale_type = fields.Selection(
        [
            ('monthly', 'Mensual'),
            ('yearly', 'Anual'),
            ('hours', 'Bono de horas'),
            ('punctual', 'Puntual'),
        ],
        string='Tipo de contrato (Cositt)',
        default='monthly',
        help='Define el tipo de contrato y la plantilla de documento que se aplicará al generarlo desde el pedido. '
             '«Bono de horas»: las horas del contrato = cantidad vendida en la línea.',
    )

    @api.constrains('cositt_contract_sale_type', 'cositt_recurring_contract')
    def _check_cositt_sale_type_requires_recurring(self):
        for tmpl in self:
            if tmpl.cositt_contract_sale_type != 'monthly' and not tmpl.cositt_recurring_contract:
                raise ValidationError(
                    _('El tipo de contrato Cositt solo aplica si el producto está marcado como contrato recurrente.')
                )

    @api.model_create_multi
    def create(self, vals_list):
        out = []
        for vals in vals_list:
            vals = dict(vals)
            if vals.get('cositt_recurring_contract') is False:
                vals['cositt_contract_sale_type'] = 'monthly'
            out.append(vals)
        return super().create(out)

    def write(self, vals):
        vals = dict(vals)
        if vals.get('cositt_recurring_contract') is False:
            vals['cositt_contract_sale_type'] = 'monthly'
        return super().write(vals)
