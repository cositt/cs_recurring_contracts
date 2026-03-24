# -*- coding: utf-8 -*-
"""Renombra la columna antigua de plantilla única a la plantilla «mensual»."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'res_company'
            AND column_name = 'cositt_default_contract_body_html'
        )
        """
    )
    if not cr.fetchone()[0]:
        return
    cr.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'res_company'
            AND column_name = 'cositt_contract_body_default_monthly'
        )
        """
    )
    if cr.fetchone()[0]:
        _logger.info('cositt_contracts: columna mensual ya existe; no se renombra.')
        return
    cr.execute(
        """
        ALTER TABLE res_company
        RENAME COLUMN cositt_default_contract_body_html TO cositt_contract_body_default_monthly
        """
    )
    _logger.info('cositt_contracts: migrada plantilla antigua a cositt_contract_body_default_monthly.')
