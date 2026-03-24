# -*- coding: utf-8 -*-
import base64
import hashlib
import logging
import secrets
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import format_date
from datetime import date
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)


class CosittSubscriptionContract(models.Model):
    _name = 'cositt.subscription.contract'
    _description = 'Contrato de Suscripción Cositt'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Nombre', required=True, copy=False, default='Nuevo')
    reference = fields.Char(string='Referencia')
    partner_id = fields.Many2one('res.partner', string='Cliente', required=True, tracking=True)
    date_start = fields.Date(string='Fecha Inicio', default=fields.Date.context_today, required=True, tracking=True)
    date_end = fields.Date(string='Fecha Fin', tracking=True)
    recurring_period = fields.Integer(string='Duración', default=1)
    recurring_period_interval = fields.Selection(
        [('days', 'Días'), ('weeks', 'Semanas'), ('months', 'Meses'), ('years', 'Años')],
        string='Unidad', default='months')
    recurring_invoice = fields.Integer(string='Intervalo Facturación (Días)', default=30)
    next_invoice_date = fields.Date(string='Próx. Factura', tracking=True)
    contract_reminder = fields.Integer(string='Aviso (Días)', default=7)

    state = fields.Selection([
        ('New', 'Nuevo'),
        ('Ongoing', 'En Curso'),
        ('Expire_Soon', 'Vence Pronto'),
        ('Expired', 'Expirado'),
        ('Cancelled', 'Cancelado'),
    ], default='New', tracking=True)
    lock = fields.Boolean(string='Bloqueado', default=False)
    amount_total = fields.Monetary(string='Total', compute='_compute_amount_total')
    invoice_count = fields.Integer(string='Facturas', compute='_compute_invoice_count')

    company_id = fields.Many2one('res.company', string='Empresa', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    auto_invoice_on_sign = fields.Boolean(
        string='Generar 1.ª factura al firmar (portal)',
        default=lambda self: self.env.company.cositt_auto_invoice_on_contract_sign,
        help='Si está activo, al firmar en el portal se crea y publica la primera factura según las líneas del contrato. El valor por defecto viene de la empresa; puede cambiarse en cada contrato.',
    )

    contract_line_ids = fields.One2many(
        'cositt.subscription.contract.line', 'subscription_contract_id', string='Líneas del Contrato')
    sale_order_id = fields.Many2one(
        'sale.order', string='Pedido de venta', index=True, copy=False, ondelete='set null', tracking=True,
    )
    parent_contract_id = fields.Many2one(
        'cositt.subscription.contract',
        string='Contrato principal',
        index=True,
        copy=False,
        ondelete='set null',
        help='Anexos recurrentes: contrato padre generado en el mismo pedido.',
    )
    child_contract_ids = fields.One2many(
        'cositt.subscription.contract', 'parent_contract_id', string='Contratos anexo',
    )
    child_contract_count = fields.Integer(compute='_compute_child_contract_count')

    sale_order_line_ids = fields.One2many(
        'sale.order.line', 'contract_origin', string='Líneas (Órdenes Venta)')
    invoice_ids = fields.One2many('account.move', 'contract_origin', string='Facturas')
    note = fields.Html(string='Notas adicionales')
    contract_body_html = fields.Html(
        string='Cuerpo del contrato (plantilla)',
        sanitize=False,
        help='Texto legal del contrato. Puede incluir datos dinámicos del cliente y del contrato con sintaxis Jinja, '
             'por ejemplo: {{ object.partner_id.name }}, {{ object.partner_id.vat }}, {{ object.date_start }}, '
             '{{ object.amount_total }}, {{ object.company_id.name }}. Tras guardar, use la vista previa inferior.',
    )
    contract_body_rendered = fields.Html(
        string='Vista previa (texto resuelto)',
        compute='_compute_contract_body_rendered',
        sanitize=False,
    )

    contract_type = fields.Selection([
        ('monthly', 'Mensual'),
        ('yearly', 'Anual'),
        ('hours', 'Bono Horas'),
        ('punctual', 'Puntual'),
    ], string='Tipo', default='monthly', required=True, tracking=True)
    invoice_day = fields.Integer(string='Día de Facturación', default=1)
    hours_total = fields.Float(string='Bono (Total)')
    hours_consumed = fields.Float(string='Consumo', compute='_compute_hours_consumed', tracking=True)
    hours_bundle_exhausted = fields.Boolean(
        string='Bono agotado',
        compute='_compute_hours_consumed',
        help='Indica si las horas imputadas al proyecto han alcanzado el total del bono.',
    )
    project_id = fields.Many2one(
        'project.project',
        string='Proyecto (bono horas)',
        copy=False,
        ondelete='set null',
        help='Generado automáticamente para contratos tipo «Bono horas». Las horas imputadas en el proyecto descuentan el bono.',
    )

    signature_required = fields.Boolean(
        string='Requiere firma del cliente',
        default=True,
        help='Si está activo, el contrato debe aceptarse por el cliente en el enlace web antes de activar la recurrencia y la facturación automática. Si lo desactiva, use «Confirmar (sin firma web)» en lugar de «Enviar para firma».',
    )
    signature_state = fields.Selection([
        ('na', 'No requerida'),
        ('pending', 'Pendiente de envío'),
        ('sent', 'Enviado al cliente'),
        ('signed', 'Firmado'),
    ], string='Estado de la firma', default='na', tracking=True, copy=False)
    access_token = fields.Char(string='Token portal', copy=False, index=True)
    signed_on = fields.Datetime(string='Firmado el', readonly=True, copy=False)
    signed_ip = fields.Char(string='IP en firma', readonly=True, copy=False)
    signed_user_agent = fields.Text(string='Navegador (User-Agent)', readonly=True, copy=False)
    signature_evidence_hash = fields.Char(
        string='Huella evidencia (SHA-256)',
        readonly=True,
        copy=False,
        help='Resumen criptográfico del bloque de datos de aceptación (contrato, fecha, IP, agente).',
    )
    signature_attachment_id = fields.Many2one(
        'ir.attachment',
        string='Constancia PDF',
        readonly=True,
        copy=False,
        ondelete='set null',
    )

    sign_url = fields.Char(string='Enlace firma (correo)', compute='_compute_sign_url')
    signature_report_url = fields.Char(
        string='Abrir constancia PDF',
        compute='_compute_signature_report_url',
        help='URL del informe QWeb de constancia (sesión Odoo requerida). También: menú Imprimir en la cabecera del formulario.',
    )

    @api.depends('access_token')
    def _compute_sign_url(self):
        for r in self:
            r.sign_url = r._get_public_sign_url()

    @api.depends('signature_state')
    def _compute_signature_report_url(self):
        report = self.env.ref('cositt_contracts.action_report_signature_evidence', raise_if_not_found=False)
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        for r in self:
            if not report or r.signature_state != 'signed' or not r.id:
                r.signature_report_url = False
                continue
            r.signature_report_url = '%s/report/pdf/%s/%s' % (base.rstrip('/'), report.report_name, r.id)

    def _get_public_sign_url(self):
        """URL absoluta para el cliente (correo / documentación)."""
        self.ensure_one()
        if not self.access_token:
            return ''
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        return '%s/cositt/contract/%s' % (base.rstrip('/'), self.access_token)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('signature_required') is False:
                vals['signature_state'] = 'na'
            elif vals.get('signature_required'):
                vals.setdefault('signature_state', 'pending')
            if not vals.get('contract_body_html'):
                cid = vals.get('company_id') or self.env.context.get('default_company_id') or self.env.company.id
                company = self.env['res.company'].browse(cid)
                ctype = vals.get('contract_type') or 'monthly'
                body = company.cositt_default_contract_body_for_type(ctype)
                if body:
                    vals['contract_body_html'] = body
        records = super().create(vals_list)
        for rec in records:
            rec._cositt_create_hours_project()
        return records

    def write(self, vals):
        vals = dict(vals)
        if vals.get('signature_required') is False:
            vals['signature_state'] = 'na'
        elif vals.get('signature_required') is True:
            if any(rec.signature_state == 'na' for rec in self):
                vals.setdefault('signature_state', 'pending')
        res = super().write(vals)
        for rec in self:
            rec._cositt_create_hours_project()
        return res

    @api.depends('child_contract_ids')
    def _compute_child_contract_count(self):
        for r in self:
            r.child_contract_count = len(r.child_contract_ids)

    @api.depends('contract_line_ids.sub_total')
    def _compute_amount_total(self):
        for r in self:
            r.amount_total = sum(l.sub_total for l in r.contract_line_ids)

    @api.depends(
        'contract_body_html',
        'partner_id',
        'name',
        'reference',
        'date_start',
        'date_end',
        'amount_total',
        'sale_order_id',
        'company_id',
        'contract_type',
        'hours_total',
        'hours_consumed',
        'currency_id',
        'next_invoice_date',
        'recurring_invoice',
        'recurring_period',
        'recurring_period_interval',
        'contract_line_ids',
    )
    def _compute_contract_body_rendered(self):
        MailTemplate = self.env['mail.template']
        for rec in self:
            if not rec.contract_body_html:
                rec.contract_body_rendered = False
                continue
            try:
                out = MailTemplate._render_template(
                    rec.contract_body_html,
                    'cositt.subscription.contract',
                    rec.ids,
                    engine='inline_template',
                )
                rec.contract_body_rendered = out.get(rec.id) or ''
            except Exception as err:
                _logger.warning(
                    'cositt_contracts: no se pudo renderizar contract_body_html (id=%s): %s', rec.id, err
                )
                rec.contract_body_rendered = (
                    '<p class="text-danger"><em>%s</em></p>'
                    % _('Error al resolver la plantilla. Revise la sintaxis o los datos del contrato.')
                )

    @api.depends('invoice_ids')
    def _compute_invoice_count(self):
        for r in self:
            r.invoice_count = len(r.invoice_ids)

    @api.depends('contract_type', 'hours_total', 'project_id', 'sale_order_line_ids.qty_delivered')
    def _compute_hours_consumed(self):
        for r in self:
            consumed = 0.0
            if r.contract_type == 'hours':
                if r.project_id:
                    aml = self.env['account.analytic.line'].sudo().search([('project_id', '=', r.project_id.id)])
                    consumed = sum(aml.mapped('unit_amount'))
            else:
                consumed = sum(r.sale_order_line_ids.mapped('qty_delivered'))
            r.hours_consumed = consumed
            r.hours_bundle_exhausted = bool(
                r.contract_type == 'hours' and r.hours_total > 0 and consumed >= r.hours_total - 1e-9
            )

    def _cositt_create_hours_project(self):
        """Crea el proyecto del bono (paquete ya facturado; seguimiento por horas en proyecto)."""
        self.ensure_one()
        if self.contract_type != 'hours' or self.project_id:
            return
        if not self.hours_total:
            return
        Project = self.env['project.project']
        name = _('Bono horas: %s') % (self.name or str(self.id))
        if self.sale_order_id:
            name = '%s | %s' % (self.sale_order_id.name, self.name or self.reference or '')
        vals = {
            'name': name,
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
        }
        if 'sale_order_id' in Project._fields and self.sale_order_id:
            vals['sale_order_id'] = self.sale_order_id.id
        if 'allow_billable' in Project._fields:
            vals['allow_billable'] = True
        project = Project.create(vals)
        if 'allocated_hours' in project._fields:
            try:
                project.write({'allocated_hours': self.hours_total})
            except Exception as err:
                _logger.warning(
                    'cositt_contracts: no se pudo fijar allocated_hours en el proyecto %s: %s',
                    project.id, err,
                )
        self.project_id = project.id

    def action_open_hours_project(self):
        self.ensure_one()
        if not self.project_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Proyecto del bono'),
            'res_model': 'project.project',
            'res_id': self.project_id.id,
            'view_mode': 'form',
        }

    def _is_signature_ok_for_billing(self):
        self.ensure_one()
        if not self.signature_required:
            return True
        return self.signature_state == 'signed'

    def _cositt_portal_duration_reference_line(self):
        """Texto de duración/periodicidad alineado con la modalidad (evita p. ej. «1 Meses» en anual)."""
        self.ensure_one()
        ct = self.contract_type
        n = self.recurring_period
        interval = self.recurring_period_interval
        interval_labels = dict(self._fields['recurring_period_interval'].selection)
        unit = interval_labels.get(interval, '') if interval else ''

        if ct == 'yearly':
            if n and interval == 'years':
                return _('Duración convenida (referencia): %(n)s %(unit)s.') % {'n': n, 'unit': unit}
            return False
        if ct == 'monthly':
            if n and interval == 'months':
                unit_txt = _('meses') if (n or 0) != 1 else _('mes')
                return _('Duración convenida (referencia): %(n)s %(unit)s.') % {'n': n, 'unit': unit_txt}
            return False
        if ct == 'hours':
            if n and interval:
                return _('Duración convenida (referencia): %(n)s %(unit)s (bono de horas).') % {'n': n, 'unit': unit}
            return False
        if ct == 'punctual':
            if n and interval:
                return _('Duración convenida (referencia): %(n)s %(unit)s.') % {'n': n, 'unit': unit}
            return False
        if n and interval:
            return _('Duración convenida (referencia): %(n)s %(unit)s.') % {'n': n, 'unit': unit}
        return False

    def cositt_portal_recurrence_line_list(self):
        """Textos de recurrencia para la página pública de firma."""
        self.ensure_one()
        lines = []
        env = self.env
        labels = dict(self._fields['contract_type'].selection)
        mod = labels.get(self.contract_type, self.contract_type)
        lines.append(_('Modalidad: %s') % mod)

        if self.contract_type == 'monthly':
            lines.append(_('Facturación mensual: día %(day)s de cada mes.') % {'day': self.invoice_day})
            if self.date_start:
                nxt = self.date_start + relativedelta(months=1)
                lines.append(
                    _('Próxima facturación mensual (referencia, tras el primer ciclo): %s')
                    % format_date(env, nxt)
                )
        elif self.contract_type == 'yearly':
            lines.append(
                _('Facturación anual: un ciclo cada 12 meses en la misma fecha (aniversario del inicio de vigencia).')
            )
            if self.date_start:
                nxt_year = self.date_start + relativedelta(years=1)
                lines.append(
                    _('Próxima facturación anual (referencia): %s (mismo día y mes, año siguiente).')
                    % format_date(env, nxt_year)
                )
            elif self.invoice_day:
                lines.append(
                    _('Día del mes para comprobación de facturación automática: %(day)s.') % {'day': self.invoice_day}
                )
        elif self.contract_type == 'hours':
            if self.hours_total:
                lines.append(_('Bono de horas: %s h.') % self.hours_total)
            lines.append(_('Consumo por horas imputadas al proyecto vinculado al contrato.'))
        elif self.contract_type == 'punctual':
            lines.append(_('Intervalo entre facturas: %s días.') % self.recurring_invoice)
            if self.date_start and self.recurring_invoice:
                nxt = self.date_start + relativedelta(days=self.recurring_invoice)
                lines.append(
                    _('Próxima facturación (referencia): %s') % format_date(env, nxt)
                )

        dur = self._cositt_portal_duration_reference_line()
        if dur:
            lines.append(dur)

        if self.date_start:
            lines.append(_('Inicio de vigencia: %s') % format_date(env, self.date_start))
        if self.date_end:
            lines.append(_('Fin de vigencia: %s') % format_date(env, self.date_end))
        if self.next_invoice_date:
            lines.append(
                _('Primera fecha de facturación prevista en sistema: %s') % format_date(env, self.next_invoice_date)
            )
        return lines

    def cositt_portal_sale_line_recordset(self):
        """Líneas del pedido vinculadas a este contrato (contract_origin), no todo el pedido."""
        self.ensure_one()
        linked = self.sale_order_line_ids.filtered(lambda l: not l.display_type)
        if linked:
            return linked
        if self.sale_order_id:
            return self.sale_order_id.order_line.filtered(lambda l: not l.display_type)
        return self.env['sale.order.line']

    def _set_initial_next_invoice_date(self):
        """Primera fecha de factura tras activar el contrato (confirmación o firma)."""
        for r in self:
            if r.next_invoice_date:
                continue
            today = date.today()
            start = r.date_start
            if not start:
                continue
            r.next_invoice_date = start if start >= today else today

    def action_send_for_signature(self):
        self.ensure_one()
        if not self.signature_required:
            raise UserError(_('Este contrato no requiere firma electrónica.'))
        if self.state != 'New':
            raise UserError(_('Solo se puede enviar a firmar en estado Nuevo.'))
        if not self.contract_line_ids:
            raise UserError(_('Añada al menos una línea al contrato.'))
        if not self.partner_id.email:
            raise UserError(_('Indique un correo electrónico en el contacto del cliente.'))
        vals = {'signature_state': 'sent'}
        if not self.access_token:
            vals['access_token'] = secrets.token_urlsafe(32)
        self.write(vals)
        template = self.env.ref('cositt_contracts.mail_template_contract_sign_request', raise_if_not_found=False)
        if template:
            template.send_mail(self.id, force_send=True)
        self.message_post(body=_('Enlace de firma enviado al cliente.'))
        return True

    def _compute_signature_evidence_hash(self, signed_on_dt, ip, user_agent):
        """Cadena acordada para la huella (no incluye el propio hash)."""
        self.ensure_one()
        ua = (user_agent or '')[:500]
        parts = [
            str(self.id),
            (self.name or '').strip(),
            str(self.partner_id.id),
            str(self.company_id.id),
            fields.Datetime.to_string(signed_on_dt),
            '%.2f' % (self.amount_total or 0.0),
            self.currency_id.name or '',
            (ip or '').strip(),
            ua,
        ]
        return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()

    def _generate_signature_evidence_pdf(self):
        """Genera el PDF de constancia y lo guarda en ir.attachment."""
        self.ensure_one()
        if not self.env.ref('cositt_contracts.action_report_signature_evidence', raise_if_not_found=False):
            return self.env['ir.attachment']
        try:
            pdf_content, _fmt = self.env['ir.actions.report'].with_context(
                report_pdf_no_attachment=True,
            )._render_qweb_pdf(
                'cositt_contracts.action_report_signature_evidence',
                self.ids,
            )
        except Exception as e:
            _logger.exception('cositt_contracts: no se pudo generar constancia PDF: %s', e)
            return self.env['ir.attachment']
        name = _('Constancia firma %s.pdf') % (self.name or str(self.id))
        if self.signature_attachment_id:
            self.signature_attachment_id.unlink()
        att = self.env['ir.attachment'].create({
            'name': name,
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
        self.signature_attachment_id = att
        return att

    def action_finalize_portal_signature(self, portal_meta=None):
        """Llamado desde el controlador público (sudo). Activa recurrencia (En curso + primera factura)."""
        self.ensure_one()
        portal_meta = portal_meta or {}
        if self.state in ('Cancelled', 'Expired'):
            raise UserError(_('Este contrato no admite firma.'))
        if not self.signature_required:
            raise UserError(_('Este contrato no requiere firma.'))
        if self.signature_state == 'signed':
            return True
        if self.signature_state != 'sent':
            raise UserError(_('El contrato debe estar enviado al cliente antes de firmar.'))
        now = fields.Datetime.now()
        ip = (portal_meta.get('ip') or '')[:45]
        ua = (portal_meta.get('user_agent') or '')[:2000]
        ev_hash = self._compute_signature_evidence_hash(now, ip, ua)
        self.write({
            'signature_state': 'signed',
            'signed_on': now,
            'signed_ip': ip or False,
            'signed_user_agent': ua or False,
            'signature_evidence_hash': ev_hash,
            'state': 'Ongoing',
        })
        self._set_initial_next_invoice_date()
        att = self._generate_signature_evidence_pdf()
        body = _(
            'Contrato aceptado por el cliente vía portal.\n'
            'IP: %(ip)s\n'
            'Huella de evidencia (SHA-256): %(h)s',
            ip=ip or '-',
            h=ev_hash,
        )
        msg_vals = {'body': body}
        if att:
            msg_vals['attachment_ids'] = [att.id]
        self.message_post(**msg_vals)
        tpl = self.env.ref('cositt_contracts.mail_template_contract_signed_customer_copy', raise_if_not_found=False)
        if tpl and self.partner_id.email:
            try:
                if att:
                    tpl.send_mail(
                        self.id,
                        force_send=True,
                        email_values={'attachment_ids': [att.id]},
                    )
                else:
                    tpl.send_mail(self.id, force_send=True)
            except Exception as e:
                _logger.warning('cositt_contracts: no se pudo enviar copia al cliente: %s', e)
        if self.auto_invoice_on_sign:
            try:
                self.action_generate_invoice()
                self.message_post(
                    body=_('Primera factura generada automáticamente al firmar (opción activada en el contrato).'),
                )
            except Exception as e:
                _logger.exception('cositt_contracts: factura automática tras firma: %s', e)
                self.message_post(
                    body=_('No se pudo generar la factura automática al firmar: %s') % str(e),
                )
        return True

    def action_to_confirm(self):
        for r in self:
            if r.signature_required and r.signature_state != 'signed':
                raise UserError(_(
                    'Este contrato requiere firma del cliente. Use «Enviar para firma» o desactive «Requiere firma del cliente».'
                ))
            r.state = 'Ongoing'
            r._set_initial_next_invoice_date()

    def action_to_cancel(self):
        for r in self:
            r.state = 'Cancelled'

    def action_lock(self):
        for r in self:
            r.lock = True

    def action_to_unlock(self):
        for r in self:
            r.lock = False

    def action_get_invoice(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Facturas'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('contract_origin', '=', self.id)],
        }

    def action_generate_invoice(self):
        for r in self:
            if not r._is_signature_ok_for_billing():
                raise UserError(_('El contrato debe estar firmado por el cliente antes de facturar.'))
            inv = self.env['account.move'].create(r._prepare_invoice_vals())
            inv.action_post()
            if r.next_invoice_date:
                if r.contract_type == 'monthly':
                    r.next_invoice_date += relativedelta(months=1)
                elif r.contract_type == 'yearly':
                    r.next_invoice_date += relativedelta(years=1)
                else:
                    r.next_invoice_date += relativedelta(days=r.recurring_invoice)
        return True

    def _prepare_invoice_vals(self):
        self.ensure_one()
        jrnl = self.env['account.journal'].search([
            ('type', '=', 'sale'), ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not jrnl:
            raise UserError(_('No hay un diario de ventas configurado para la empresa %s.') % self.company_id.display_name)
        lines = [(0, 0, {
            'product_id': l.product_id.id,
            'name': l.description or l.product_id.name,
            'quantity': l.qty_ordered,
            'product_uom_id': l.product_uom_id.id,
            'price_unit': l.price_unit,
            'tax_ids': [(6, 0, l.tax_ids.ids)],
            'discount': l.discount,
        }) for l in self.contract_line_ids]
        return {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'currency_id': self.currency_id.id,
            'journal_id': jrnl.id,
            'contract_origin': self.id,
            'invoice_line_ids': lines,
        }

    @api.model
    def subscription_contract_state_change(self):
        today = date.today()
        contracts_to_check = self.search([('state', 'in', ['New', 'Ongoing', 'Expire_Soon'])])
        new_invoices = self.env['account.move']
        for c in contracts_to_check:
            if c.signature_required and c.signature_state != 'signed':
                continue
            if c.date_end:
                rem = c.date_end - relativedelta(days=c.contract_reminder)
                if today > c.date_end:
                    c.state = 'Expired'
                    continue
                elif today >= rem:
                    c.state = 'Expire_Soon'
            if c.next_invoice_date and c.next_invoice_date <= today:
                if c.invoice_day and c.contract_type not in ['punctual', 'hours'] and today.day != c.invoice_day:
                    continue
                inv = self.env['account.move'].create(c._prepare_invoice_vals())
                inv.action_post()
                new_invoices += inv
                if c.contract_type == 'monthly':
                    c.next_invoice_date += relativedelta(months=1)
                elif c.contract_type == 'yearly':
                    c.next_invoice_date += relativedelta(years=1)
                else:
                    c.next_invoice_date += relativedelta(days=c.recurring_invoice)
                t = self.env.ref('account.email_template_edi_invoice', False)
                if t:
                    t.send_mail(inv.id, force_send=True)
        if new_invoices:
            self.env['account.move']._generate_sepa_batch(new_invoices)


class CosittSubscriptionContractLine(models.Model):
    _name = 'cositt.subscription.contract.line'
    _description = 'Línea de Contrato'
    subscription_contract_id = fields.Many2one('cositt.subscription.contract', ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    description = fields.Text()
    qty_ordered = fields.Float(default=1.0)
    product_uom_id = fields.Many2one('uom.uom')
    price_unit = fields.Float()
    tax_ids = fields.Many2many('account.tax')
    discount = fields.Float()
    sub_total = fields.Monetary(compute='_compute_sub_total')
    currency_id = fields.Many2one(related='subscription_contract_id.currency_id')

    @api.depends('qty_ordered', 'price_unit', 'discount')
    def _compute_sub_total(self):
        for r in self:
            r.sub_total = r.price_unit * (1 - (r.discount or 0) / 100.0) * r.qty_ordered

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.description = self.product_id.display_name
            self.price_unit = self.product_id.list_price
            self.product_uom_id = self.product_id.uom_id.id


class AccountMove(models.Model):
    _inherit = 'account.move'
    contract_origin = fields.Many2one('cositt.subscription.contract', 'Contrato')

    @api.model
    def _generate_sepa_batch(self, invoices):
        if not invoices:
            return
        pml = self.env['account.payment.method.line'].search([
            ('code', '=', 'sepa_direct_debit'), ('payment_type', '=', 'inbound'),
        ], limit=1)
        if not pml:
            return
        payments = self.env['account.payment']
        for i in invoices:
            if i.state != 'posted' or i.payment_state in ('paid', 'in_payment'):
                continue
            p = self.env['account.payment'].create({
                'date': date.today(),
                'amount': i.amount_residual,
                'payment_type': 'inbound',
                'partner_type': 'customer',
                'ref': i.name or i.payment_reference,
                'journal_id': pml.journal_id.id or i.journal_id.id,
                'currency_id': i.currency_id.id,
                'partner_id': i.partner_id.id,
                'payment_method_line_id': pml.id,
            })
            p.action_post()
            lines = (i.line_ids + p.line_ids).filtered(
                lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled)
            if len(lines) > 1:
                lines.reconcile()
            payments += p
        if payments and 'account.batch.payment' in self.env:
            self.env['account.batch.payment'].create({
                'journal_id': payments[0].journal_id.id,
                'payment_ids': [(6, 0, payments.ids)],
                'payment_method_id': pml.payment_method_id.id,
                'batch_type': 'inbound',
            })
