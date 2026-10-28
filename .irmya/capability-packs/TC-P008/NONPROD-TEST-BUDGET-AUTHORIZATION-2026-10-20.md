# TC-P008 — Presupuesto y autorización cerrados (2026-10-20)

## Autorización del operador

- Pruebas aprobadas: (1) contención concurrente real de clave única en PostgreSQL aislado; (2) terminación real de Worker posterior a commit; (3) pérdida real de ACK a nivel transporte con recuperación y prueba de idempotencia.
- Ámbito: recursos NONPROD exclusivos. Prohibidos producción, tráfico de clientes, cobros, Queue compartida, cambios de rutas comerciales.
- **Presupuesto máximo agregado autorizado: USD 10.00** para las tres pruebas, incluyendo aprovisionamiento, cómputo, Queue, almacenamiento y limpieza. Este límite es **total**, no USD 10 por experimento.
- Regla fail-closed: si el coste acumulado, comprometido o inevitable no puede acotarse por debajo de USD 10, suspender cualquier operación facturable y solicitar decisión; no suponer que un plan gratuito garantiza gasto 0.
- No se ha autorizado exponer ninguna contraseña ni transmitir secretos por conversación, Git, logs ni argumentos de procesos.

## Preflight económico y técnico

- Cloudflare Queues factura operaciones de escritura, lectura y borrado según consumo; pueden existir operaciones incluidas, pero depende del plan y uso total de la cuenta. Referencia oficial: https://developers.cloudflare.com/queues/platform/pricing/
- Supabase factura instancias activas por horas y el límite de gasto de la plataforma no necesariamente limita el cómputo; consultar consumo real del proyecto y créditos antes de iniciar recursos adicionales. Referencia oficial: https://supabase.com/docs/guides/platform/manage-your-usage/compute
- Proyecto existente `trendcite-tcp008-sandbox` activo; identidad `tc_p008_probe_login` aún caducada (`2026-10-18 23:59 UTC`) y sin contraseña, confirmado por catálogo read-only.
- Hasta disponer de credencial temporal con custodia nativa, no se puede probar la condición de dos sesiones restringidas e independientes.
- No hay Worker de fallo exclusivo verificado; `trendcite-nonprod-runtime` consume la Queue existente y nunca debe utilizarse para inyección destructiva.

## Secuencia condicionada

1. Confirmar plan, consumo y coste comprometido de Supabase/Cloudflare; definir un contador real y un límite de tiempo que no pueda superar USD 10.
2. Provisionar en canal protegido del proveedor credencial efímera restringida del sandbox; verificar exclusivamente metadatos del rol y probar identidad TLS y dos sesiones independientes sin revelar la credencial.
3. Crear solo recursos exclusivos que sean reversibles y compatibles con presupuesto; auditar cero rutas ajenas, productores/consumidores de otros proyectos, permisos inesperados.
4. Ejecutar cada experimento una única vez con marcadores sintéticos, observabilidad independiente y evidencia de proveedor; abortar si el proveedor no permite demostrar una terminación real o una pérdida real de ACK.
5. Confirmar limpieza dirigida, cero residuos y mensajes pendientes, eliminación de recursos de prueba, revocación de credencial, desglose de gasto y actualización de matriz únicamente con pruebas reales.

## Estado tras fijar el presupuesto

`TC_P008_NONPROD_TEST_BUDGET_USD=10.00`
`BUDGET_AUTHORIZED=YES`
`BUDGET_SPENT_BY_THIS_EXECUTION=0_UNVERIFIED_PROVIDER_TOTAL`
`HOSTED_PROBES=NOT_RUN`
`CREDENTIAL_GATE=BLOCKED`
`ISOLATED_WORKER_QUEUE_GATE=BLOCKED`
`PRODUCTION=DARK`
`COMMERCIALIZATION=HOLD`
`PR_121=DRAFT`
