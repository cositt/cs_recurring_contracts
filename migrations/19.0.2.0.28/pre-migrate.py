# -*- coding: utf-8 -*-
"""Antes de eliminar cositt_contract_hours_bundle, guarda los productos que eran bono horas."""
import json
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'product_template'
            AND column_name = 'cositt_contract_hours_bundle'
        )
        """
    )
    if not cr.fetchone()[0]:
        return
    cr.execute(
        """
        SELECT id FROM product_template WHERE cositt_contract_hours_bundle IS TRUE
        """
    )
    ids = [r[0] for r in cr.fetchall()]
    if not ids:
        return
    cr.execute(
        """
        INSERT INTO ir_config_parameter (key, value)
        VALUES ('cositt_contracts.migrate_hours_product_tmpl_ids', %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        (json.dumps(ids),),
    )
    _logger.info('cositt_contracts: guardados %s product.template como bono horas para migración.', len(ids))
