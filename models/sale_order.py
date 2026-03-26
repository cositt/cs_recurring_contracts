# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    cositt_contract_grouping = fields.Selection(
        [
            ('per_line', 'Un contrato por cada producto recurrente (recomendado)'),
            ('grouped', 'Un solo contrato para todos los productos recurrentes'),
        ],
        string='Modo contratos recurrentes',
        default='per_line',
        help='Por defecto: un contrato por cada línea de pedido con producto recurrente (sin anexo). '
             '«Un solo contrato» agrupa todas esas líneas en un único contrato. '
             'Los anexos (línea principal indicada) generan siempre un contrato aparte.',
    )
    cositt_contract_ids = fields.One2many(
        'cositt.subscription.contract', 'sale_order_id', string='Contratos Cositt',
    )
    cositt_contract_count = fields.Integer(compute='_compute_cositt_contract_count')

    @api.depends('cositt_contract_ids')
    def _compute_cositt_contract_count(self):
        for order in self:
            order.cositt_contract_count = len(order.cositt_contract_ids)

    def _action_confirm(self):
        """Odoo 19: action_confirm escribe state=sale y llama a _action_confirm."""
        res = super()._action_confirm()
        for order in self:
            order._cositt_create_contracts_from_sale()
        return res

    def _cositt_recurring_lines(self):
        self.ensure_one()
        return self.order_line.filtered(
            lambda l: l.product_id and l.product_id.product_tmpl_id.cositt_recurring_contract
        )

    def _cositt_sol_tax_ids(self, sol):
        if 'tax_id' in sol._fields:
            return sol.tax_id.ids
        if 'tax_ids' in sol._fields:
            return sol.tax_ids.ids
        return []

    def _cositt_prepare_contract_line_vals_from_sol(self, sol):
        return {
            'product_id': sol.product_id.id,
            'description': sol.name,
            'qty_ordered': sol.product_uom_qty,
            'product_uom_id': sol.product_uom_id.id,
            'price_unit': sol.price_unit,
            'discount': sol.discount,
            'tax_ids': [(6, 0, self._cositt_sol_tax_ids(sol))],
        }

    def _cositt_contract_type_and_hours_from_sols(self, sol_records):
        """Tipo de contrato y horas totales según el tipo definido en cada producto (Cositt)."""
        if not sol_records:
            return 'monthly', 0.0
        tmpls = sol_records.mapped('product_id.product_tmpl_id')
        types_list = [t.cositt_contract_sale_type or 'monthly' for t in tmpls]
        if len(set(types_list)) > 1:
            raise UserError(_(
                'No puede mezclar en el mismo contrato productos con distinto tipo Cositt '
                '(mensual, anual, bono de horas, puntual). Use el modo «un contrato por producto» o líneas homogéneas.'
            ))
        contract_type = types_list[0]
        if contract_type == 'hours':
            return 'hours', sum(sol_records.mapped('product_uom_qty'))
        return contract_type, 0.0

    def _cositt_create_contract_from_vals(self, name, sol_records, parent_contract=None):
        """Crea un contrato y enlaza contract_origin en las líneas del pedido."""
        self.ensure_one()
        order = self
        if not sol_records:
            raise UserError(_('No hay líneas de pedido para generar el contrato.'))
        line_vals = [order._cositt_prepare_contract_line_vals_from_sol(sol) for sol in sol_records]
        contract_type, hours_total = order._cositt_contract_type_and_hours_from_sols(sol_records)
        vals = {
            'name': name,
            'partner_id': order.partner_id.id,
            'company_id': order.company_id.id,
            'reference': order.name,
            'date_start': order.date_order.date() if order.date_order else fields.Date.context_today(order),
            'sale_order_id': order.id,
            'parent_contract_id': parent_contract.id if parent_contract else False,
            'signature_required': True,
            'contract_type': contract_type,
            'hours_total': hours_total if contract_type == 'hours' else 0.0,
            'contract_line_ids': [(0, 0, lv) for lv in line_vals],
        }
        body = order.company_id.cositt_default_contract_body_for_type(contract_type)
        if body:
            vals['contract_body_html'] = body
        contract = self.env['cositt.subscription.contract'].create(vals)
        sol_records.write({'contract_origin': contract.id})
        return contract

    def _cositt_create_contracts_from_sale(self):
        self.ensure_one()
        if self.cositt_contract_ids:
            return
        recurring = self._cositt_recurring_lines()
        if not recurring:
            return
        roots = recurring.filtered(lambda l: not l.cositt_parent_line_id)
        annexes = recurring - roots
        if not roots:
            raise UserError(_(
                'Hay líneas recurrentes solo como anexo; debe existir al menos una línea raíz recurrente (sin «Línea contrato principal»).'
            ))
        order = self
        for ax in annexes:
            if not ax.cositt_parent_line_id or ax.cositt_parent_line_id.order_id != order:
                raise UserError(_('Línea «%s»: anexo con línea principal inválida.') % (ax.name or '')[:80])
            if ax.cositt_parent_line_id.cositt_parent_line_id:
                raise UserError(_('Un anexo no puede depender de otro anexo (línea «%s»).') % (ax.name or '')[:80])
            if ax.cositt_parent_line_id not in recurring:
                raise UserError(_('La línea principal de un anexo debe ser un producto recurrente (línea «%s»).') % (ax.name or '')[:80])

        main_by_sol = {}

        if order.cositt_contract_grouping == 'grouped':
            main_contract = order._cositt_create_contract_from_vals(
                _('%s / Contrato recurrente') % (order.name or ''),
                roots,
            )
            for r in roots:
                main_by_sol[r.id] = main_contract
            for ax in annexes:
                parent_sol = ax.cositt_parent_line_id
                parent_ct = main_by_sol.get(parent_sol.id)
                if not parent_ct:
                    raise UserError(_('No se encontró contrato principal para el anexo «%s».') % (ax.name or '')[:80])
                order._cositt_create_contract_from_vals(
                    _('%s / Anexo: %s') % (order.name or '', ax.product_id.display_name),
                    ax,
                    parent_contract=parent_ct,
                )
        else:
            for r in roots:
                ct = order._cositt_create_contract_from_vals(
                    _('%s / %s') % (order.name or '', r.product_id.display_name),
                    r,
                )
                main_by_sol[r.id] = ct
            for ax in annexes:
                parent_sol = ax.cositt_parent_line_id
                parent_ct = main_by_sol.get(parent_sol.id)
                if not parent_ct:
                    raise UserError(_('No se encontró contrato principal para el anexo «%s».') % (ax.name or '')[:80])
                order._cositt_create_contract_from_vals(
                    _('%s / Anexo: %s') % (order.name or '', ax.product_id.display_name),
                    ax,
                    parent_contract=parent_ct,
                )

    def action_cositt_send_contracts_for_signature(self):
        self.ensure_one()
        if self.state != 'sale':
            raise UserError(_('El pedido debe estar confirmado.'))
        # Incluye «pending» (primer envío) y «sent» (reenvío del correo / enlace).
        to_send = self.cositt_contract_ids.filtered(
            lambda c: c.signature_required
            and c.state == 'New'
            and c.signature_state in ('pending', 'sent')
        )
        if not to_send:
            lines = [
                '- %s (contrato: %s, firma: %s)' % (c.name, c.state, c.signature_state)
                for c in self.cositt_contract_ids
            ]
            detail = '\n'.join(lines) if lines else _('(sin contratos vinculados)')
            raise UserError(
                _(
                    'Ningún contrato cumple las condiciones para envío desde el pedido.\n\n'
                    'Se envían contratos en estado «Nuevo», con firma requerida, y firma '
                    '«Pendiente» o «Enviado al cliente» (para reenviar el correo).\n\n'
                    'Contratos de este pedido:\n%s'
                )
                % detail
            )
        for c in to_send:
            c.action_send_for_signature()
        return True

    def action_cositt_open_contracts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contratos recurrentes'),
            'res_model': 'cositt.subscription.contract',
            'view_mode': 'list,form',
            'domain': [('sale_order_id', '=', self.id)],
            'context': {
                'default_sale_order_id': self.id,
                'default_partner_id': self.partner_id.id,
            },
        }


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    contract_origin = fields.Many2one('cositt.subscription.contract', string='Contrato')

    cositt_parent_line_id = fields.Many2one(
        'sale.order.line',
        string='Línea contrato principal',
        ondelete='set null',
        help='Para productos anexo recurrentes: la línea del pedido del contrato principal (mismo pedido).',
    )

    @api.constrains('cositt_parent_line_id', 'product_id', 'order_id')
    def _check_cositt_parent_line(self):
        for line in self:
            if not line.cositt_parent_line_id:
                continue
            if line.cositt_parent_line_id.order_id != line.order_id:
                raise UserError(_('La línea principal del anexo debe pertenecer al mismo pedido.'))
            if line.cositt_parent_line_id == line:
                raise UserError(_('Una línea no puede ser principal de sí misma.'))
            if not line.product_id.product_tmpl_id.cositt_recurring_contract:
                raise UserError(
                    _('Solo los productos marcados como recurrentes pueden usar anexo (línea «%s»).')
                    % (line.name or '')[:80]
                )
            if not line.cositt_parent_line_id.product_id.product_tmpl_id.cositt_recurring_contract:
                raise UserError(
                    _('La línea principal debe ser un producto recurrente (anexo «%s»).') % (line.name or '')[:80]
                )


class ResCompany(models.Model):
    """Extensión empresa: plantillas de contrato (definida aquí para evitar desincronía con vistas)."""
    _inherit = 'res.company'

    cositt_auto_invoice_on_contract_sign = fields.Boolean(
        string='Primera factura al firmar contrato (portal)',
        default=False,
        help='Valor por defecto para nuevos contratos: generar la primera factura de cliente automáticamente cuando el cliente firma en el portal.',
    )
    cositt_contract_body_default_monthly = fields.Html(
        string='Plantilla: contratos mensuales',
        translate=True,
        sanitize=False,
        help='Se aplica a contratos con tipo «Mensual». Jinja: {{ object.partner_id.name }}, {{ object.amount_total }}, etc.',
    )
    cositt_contract_body_default_yearly = fields.Html(
        string='Plantilla: contratos anuales',
        translate=True,
        sanitize=False,
        help='Se aplica a contratos con tipo «Anual».',
    )
    cositt_contract_body_default_hours = fields.Html(
        string='Plantilla: bonos / paquetes de horas',
        translate=True,
        sanitize=False,
        help='Se aplica a contratos con tipo «Bono Horas».',
    )
    cositt_contract_body_default_punctual = fields.Html(
        string='Plantilla: contratos puntuales',
        translate=True,
        sanitize=False,
        help='Se aplica a contratos con tipo «Puntual».',
    )

    def cositt_default_contract_body_for_type(self, contract_type):
        """Plantilla por defecto según el tipo de contrato (clave selection)."""
        self.ensure_one()
        mapping = {
            'monthly': self.cositt_contract_body_default_monthly,
            'yearly': self.cositt_contract_body_default_yearly,
            'hours': self.cositt_contract_body_default_hours,
            'punctual': self.cositt_contract_body_default_punctual,
        }
        return mapping.get(contract_type) or False
