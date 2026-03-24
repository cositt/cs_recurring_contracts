# -*- coding: utf-8 -*-
"""Tras crear la columna cositt_contract_sale_type, marca bono horas los productos migrados."""
import json
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        "SELECT value FROM ir_config_parameter WHERE key = 'cositt_contracts.migrate_hours_product_tmpl_ids'"
    )
    row = cr.fetchone()
    if not row or not row[0]:
        return
    try:
        ids = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        _logger.warning('cositt_contracts: JSON de migración horas inválido.')
        return
    if not ids:
        return
    cr.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'product_template'
            AND column_name = 'cositt_contract_sale_type'
        )
        """
    )
    if not cr.fetchone()[0]:
        _logger.warning('cositt_contracts: columna cositt_contract_sale_type no existe; migración horas omitida.')
        return
    cr.execute(
        """
        UPDATE product_template
        SET cositt_contract_sale_type = 'hours'
        WHERE id IN %s
        """,
        (tuple(ids),),
    )
    cr.execute("DELETE FROM ir_config_parameter WHERE key = 'cositt_contracts.migrate_hours_product_tmpl_ids'")
    _logger.info('cositt_contracts: migrados %s product.template a tipo bono horas.', len(ids))
