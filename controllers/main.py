# -*- coding: utf-8 -*-
from odoo import http
from odoo.exceptions import UserError
from odoo.http import request


class CosittContractController(http.Controller):

    @http.route(
        ['/cositt/contract/<string:access_token>'],
        type='http',
        auth='public',
        website=True,
        methods=['GET', 'POST'],
        csrf=False,
    )
    def portal_contract_sign(self, access_token, **post):
        contract = request.env['cositt.subscription.contract'].sudo().search([
            ('access_token', '=', access_token),
        ], limit=1)
        if not contract:
            return request.not_found()

        if contract.signature_state == 'signed' or request.httprequest.args.get('signed'):
            return request.render('cositt_contracts.portal_contract_signed_ok', {
                'contract': contract,
            })

        if contract.state in ('Cancelled', 'Expired'):
            return request.render('cositt_contracts.portal_contract_unavailable', {
                'contract': contract,
                'reason': 'state',
            })

        if contract.signature_state != 'sent':
            return request.render('cositt_contracts.portal_contract_unavailable', {
                'contract': contract,
                'reason': 'not_sent',
            })

        if request.httprequest.method == 'POST':
            if not post.get('accept'):
                return request.render('cositt_contracts.portal_contract_sign', {
                    'contract': contract,
                    'access_token': access_token,
                    'error': 'Debe marcar la casilla de aceptación.',
                })
            try:
                req = request.httprequest
                xff = req.headers.get('X-Forwarded-For')
                if xff:
                    client_ip = xff.split(',')[0].strip()[:45]
                else:
                    client_ip = (req.remote_addr or '')[:45]
                contract.action_finalize_portal_signature({
                    'ip': client_ip,
                    'user_agent': (req.headers.get('User-Agent') or '')[:2000],
                })
            except UserError as e:
                return request.render('cositt_contracts.portal_contract_sign', {
                    'contract': contract,
                    'access_token': access_token,
                    'error': e.args[0] if e.args else str(e),
                })
            return request.redirect('/cositt/contract/%s?signed=1' % access_token)

        return request.render('cositt_contracts.portal_contract_sign', {
            'contract': contract,
            'access_token': access_token,
            'error': None,
        })
