# Documentación técnica — `cositt_contracts`

**Nombre técnico:** `cositt_contracts`  
**Nombre mostrado:** Contratos Recurrentes a Medida (Cositt)  
**Versión:** ver `__manifest__.py` → campo `version` (única fuente de verdad).  
**Licencia:** AGPL-3  

---

## 1. Dependencias (`__manifest__.py`)

```
website, sale, sale_management, account, mail, sales_team,
project, hr_timesheet, sale_project
```

- **`website`:** rutas públicas de firma (`/cositt/contract/<token>`). No se usa Odoo Sign Enterprise.
- **`project` / `hr_timesheet` / `sale_project`:** contratos tipo **Bono horas**: creación de `project.project`, consumo desde `account.analytic.line` del proyecto, `sale_order_id` en proyecto si el campo existe.

---

## 2. Archivos de datos y vistas (resumen)

| Ruta | Contenido |
|------|-----------|
| `security/ir.model.access.csv` | Permisos contrato y líneas. |
| `views/res_company_views.xml` | Empresa: factura al firmar + 4 plantillas HTML de documento contractual. |
| `data/cron.xml` | Cron diario: `model.subscription_contract_state_change()`. |
| `data/mail_templates.xml` | Plantilla alerta bono horas (no enlazada por defecto a automatismo). |
| `data/mail_template_signature.xml` | Solicitud de firma. |
| `data/mail_template_signed_copy.xml` | Copia al cliente tras firma. |
| `report/signature_evidence_*` | PDF constancia de firma. |
| `views/product_template_views.xml` | `cositt_recurring_contract`, `cositt_contract_sale_type`. |
| `views/subscription_contract_views.xml` | Contratos: documento contractual, bono horas, alertas. |
| `views/sale_order_views.xml` | Pedido: modo contratos, línea principal anexo. |
| `views/website_templates.xml` | Portal: bloque condiciones contractuales + firma. |
| `controllers/main.py` | Ruta pública firma. |

---

## 3. Modelos

### 3.1 `cositt.subscription.contract`

- `mail.thread`, `mail.activity.mixin`.
- Tipos: `contract_type` (`monthly` / `yearly` / `hours` / `punctual`).
- **Horas:** `hours_total`, `hours_consumed` (timesheets del `project_id`), `hours_bundle_exhausted`, `project_id`. Proyecto creado en `create`/`write` vía `_cositt_create_hours_project()`.
- **Documento:** `contract_body_html`, `contract_body_rendered` (`mail.template` + motor `inline_template`).
- Firma Community: `signature_*`, `access_token`, constancia PDF, etc.
- Métodos clave: `action_send_for_signature`, `action_finalize_portal_signature`, `action_generate_invoice`, `_prepare_invoice_vals`, `subscription_contract_state_change`, `cositt_portal_*`.

### 3.2 `cositt.subscription.contract.line`

- Líneas con subtotal monetario calculado.

### 3.3 `account.analytic.line` (herencia)

- `account_analytic_line.py`: invalida cómputos de contrato horas al crear/editar/borrar líneas con `project_id`.

### 3.4 `sale.order` / `sale.order.line` / `res.company`

- Definidos en **`models/sale_order.py`**: pedido (agrupación, creación de contratos), línea (`contract_origin`, `cositt_parent_line_id`), empresa (plantillas HTML y `cositt_default_contract_body_for_type()`).

### 3.5 `account.move`

- `contract_origin`; `_generate_sepa_batch` (SEPA / lotes si existen modelos contables).

---

## 4. Producto y pedido → contrato

- **`product.template`:** `cositt_contract_sale_type` (mensual / anual / hours / punctual); restricción con `cositt_recurring_contract`.
- **`sale.order._cositt_create_contract_from_vals`:** `contract_type` y `hours_total` desde líneas; `company_id`; `contract_body_html` desde plantillas de empresa.
- Migraciones SQL en `migrations/19.0.2.0.27` (columna plantilla mensual) y `19.0.2.0.28` (productos antiguos «bono horas» boolean → `cositt_contract_sale_type`).

---

## 5. Cron

- **Código:** `model.subscription_contract_state_change()` (el `ir.cron` apunta al modelo `cositt.subscription.contract`).
- **Intervalo:** 1 día en XML.

---

## 6. Vistas Odoo 19

- Listas: **`<list>`**; acciones: `view_mode`: **list,form**.

---

## 7. Portal y firma

- Ruta pública `csrf=False`; evidencia IP/UA/hash; `message_post` con `attachment_ids` como lista de ids.
- Plantilla portal: `contract_body_rendered` cuando hay `contract_body_html`.
- **`web.base.url`:** debe coincidir con el host de prueba.

Diagrama de negocio: [FLUJO_OPERATIVO_FIRMA.md](FLUJO_OPERATIVO_FIRMA.md). Manual de usuario: [MANUAL_USO.md](../MANUAL_USO.md).

---

## 8. Despliegue y actualización

- Añadir `cositt_contracts` al `addons_path`, `-u cositt_contracts -d <base>` tras cambios de modelo/campos.
- Docker: típico `--addons-path=…/odoo/addons,/mnt/extra-addons` y credenciales BD (`--db_host`, etc.).

---

## 9. Limitaciones y notas

1. No mantener módulos duplicados de contratos con otro nombre técnico en el mismo entorno.
2. SEPA / lotes: dependen de localización y módulos contables.
3. **Multicompañía:** sin `ir.rule` extra documentadas; valorar según proyecto.

---

## 10. Addon opcional `cositt_web_home`

Módulo hermano (misma carpeta padre de addons): abre el menú de aplicaciones al entrar al backend (parche NavBar + parámetro `cositt_web_home.open_apps_grid_on_login`). **No** es dependencia de `cositt_contracts`.

---

*Cositt / Gerard Perat — documentación técnica del módulo.*
