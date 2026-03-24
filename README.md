# Contratos Recurrentes a Medida (Cositt)

Modulo para Odoo 19 orientado a gestionar contratos recurrentes desde ventas, con firma del cliente por portal web, trazabilidad de aceptacion y facturacion automatica.

La version oficial del modulo es la indicada en `__manifest__.py` (`version`).

## Alcance funcional

- Generacion de contratos desde `sale.order` al confirmar pedido.
- Dos modos de generacion: un contrato por linea recurrente o contrato agrupado.
- Soporte de anexos por linea de pedido mediante "Linea contrato principal".
- Tipos de contrato: mensual, anual, bono de horas y puntual.
- Firma por portal (Community) con token publico, captura de IP/User-Agent y huella SHA-256.
- Constancia PDF de firma y envio de copia al cliente por correo.
- Opcion de generar y publicar la primera factura al firmar.
- Facturacion periodica automatica por cron diario.
- Integracion con proyecto y timesheets en contratos tipo bono de horas.

## Dependencias

Definidas en `__manifest__.py`:

- `website`
- `sale`
- `sale_management`
- `account`
- `mail`
- `sales_team`
- `project`
- `hr_timesheet`
- `sale_project`

## Estructura principal del modulo

- `models/subscription_contract.py`: modelo principal de contrato, logica de firma, evidencias, facturacion y cron.
- `models/sale_order.py`: generacion de contratos desde pedido y relacion pedido-contratos.
- `models/product_template.py`: configuracion del producto como recurrente y tipo de contrato.
- `models/account_analytic_line.py`: refresco de consumo en bonos de horas.
- `controllers/main.py`: ruta publica de firma `/cositt/contract/<token>`.
- `views/*.xml`: formularios, listas y plantillas web/portal.
- `data/cron.xml`: tarea programada de facturacion recurrente.
- `data/mail_template_*.xml`: plantillas de correo de solicitud y confirmacion de firma.
- `report/signature_evidence_*.xml`: reporte de constancia de firma.

## Flujo operativo resumido

1. Marcar productos recurrentes en producto (`Contrato recurrente (Cositt)` y tipo).
2. Confirmar presupuesto/pedido.
3. El modulo crea contratos vinculados al pedido.
4. Enviar contrato para firma desde el boton "Enviar para firma".
5. El cliente firma en el portal publico.
6. El contrato pasa a "En curso", se guarda evidencia y se prepara la primera fecha de factura.
7. El cron diario emite facturas segun periodicidad y reglas del contrato.

## Instalacion y actualizacion

1. Anadir `cositt_contracts` al `addons_path`.
2. Actualizar lista de aplicaciones.
3. Instalar `Contratos Recurrentes a Medida (Cositt)`.
4. Tras cambios de codigo, actualizar el modulo en la base de datos.

## Documentacion complementaria

- `MANUAL_USO.md`: guia para usuarios finales (ventas y administracion).
- `FLUJO_OPERATIVO_FIRMA.md`: detalle de la firma por portal y activacion.
- `DOCUMENTACION_TECNICA.md`: detalle tecnico para mantenimiento e implementacion.

## Licencia

AGPL-3 (ver `__manifest__.py`).
