# TC-P008 — Verificación real de prerrequisitos NONPROD (2026-10-20)

Autoridad: el operador autorizó las tres pruebas aisladas; esto no constituye evidencia de ejecución/certificación.

## Lecturas efectuadas
- Supabase: proyecto `btjgozzguhuzfdueensf` (`trendcite-tcp008-sandbox`) ACTIVE_HEALTHY, Postgres 17.
- Cuenta `tc_p008_probe_login`: `rolvaliduntil=2026-10-18 23:59:00+00`, `has_password=false` (read-only catálogo). LOGIN no utilizable para dos sesiones independientes.
- Tabla `tc_p008_isolated.unique_write_probe`: existe; USAGE del esquema y permisos INSERT/DELETE constatados para el rol, sin implicar autenticación.
- Cloudflare cuenta `ISTRIADE GROUP LLC`: NONPROD Queue `trendcite-nonprod-queue`, ID `752b703ee758448d81be0bc3639abfdf`; DLQ `trendcite-nonprod-dlq`, ID `a5c3d474d01c45e085b5152575f4408e`.
- Consulta read-only del consumidor: `trendcite-nonprod-runtime` está conectado a la Queue NONPROD existente (batch_size=5, max_retries=2, max_wait_time_ms=5000; DLQ designada). Es infraestructura existente, **no una pareja Worker/Queue exclusiva** para experimentos destructivos.
- DLQ: ningún consumidor configurado.
- GitHub PR #121 sigue DRAFT, HEAD previo `116be60876037fcaa951e3a41123c18a8cc4375d` con CI SUCCESS.

## Decisión fail-closed
**NO** realizar SQL alojado de prueba con identidad administrativa de conector. **NO** insertar en la Queue NONPROD existente para simular caída de Worker o ACK perdido. **NO** crear recursos con gasto no acotado ni tocar producción. No se realizaron escrituras alojadas.

## Condiciones antes de ejecución en lote
1. Provisionar y verificar credencial temporal `tc_p008_probe_login` con canal nativo seguro, expiración, revocación y TLS estricto; no imprimir secretos.
2. Disponer de Worker + Queue + DLQ exclusivas para la prueba de terminación/ACK, sin consumidores/rutas/clientes ajenos y con observabilidad verificable. Confirmar mecanismo proveedor capaz de producir **terminación real** / **pérdida de ACK real**; una excepción de aplicación no basta.
3. Establecer presupuesto máximo autorizado para cualquier provisión o tráfico facturable, límites de duración y contador/stop automático; evidencia de coste.
4. Capturar logs independientes, ciclo exacto de dos sesiones, bloqueo, commit, winner/loser, durable count, limpieza dirigida, inspección de backends, revocación y desmantelamiento.
5. Ante cualquier fallo de aislamiento, permisos, observabilidad o limpieza: abortar y conservar NOT_VERIFIED.

`HOSTED_UNIQUE_KEY=BLOCKED_CREDENTIAL`
`WORKER_TERMINATION=BLOCKED_DEDICATED_RESOURCES`
`TRANSPORT_ACK_LOSS=BLOCKED_DEDICATED_RESOURCES`
`HOSTED_CERTIFICATION=NOT_VERIFIED`
`PRODUCTION=DARK`
`COMMERCIALIZATION=HOLD`
`PR_121=DRAFT`
