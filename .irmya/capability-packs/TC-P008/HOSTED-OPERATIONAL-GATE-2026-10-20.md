# TC-P008 — Gate operativo verificado (2026-10-20)

## Comprobaciones reales de esta intervención

- PR #121 HEAD inicial: `73cf41a894f38ff991b3d9b47c978b005aa0a32a`; GitHub Actions SUCCESS; PR DRAFT; árbol Git local limpio.
- Supabase proyecto `btjgozzguhuzfdueensf`, consulta `pg_authid`: `tc_p008_probe_login` continúa con `rolvaliduntil=2026-10-18 23:59:00+00`, `password_configured=false`.
- Cloudflare cuenta ISTRIADE GROUP LLC (`a4c8274fca447382525edd54ee20fd74`), inventario GET /workers/scripts: solo `trendcite-nonprod-runtime` y `trendcite-prod-runtime` para TrendCite. No se identifica Worker dedicado al experimento de terminación/ACK.
- Inventario anterior confirmado en el mismo día: `trendcite-nonprod-queue` y `trendcite-nonprod-dlq` existen, con consumidor `trendcite-nonprod-runtime` conectado a Queue. No deben reutilizarse para inyección de fallos.

## Límite efectivo y secuencia de desbloqueo

1. **Credencial**: el operador deberá provisionar mediante interfaz nativa y protegida una contraseña temporal y nueva expiración del rol restringido en el sandbox dedicado. No enviar, registrar ni imprimir secretos. Verificar por consulta solo indicadores `password_configured`, vencimiento, permisos mínimos; después ejecutar autenticación de dos sesiones distintas bajo TLS estricto sin revelar DSN.
2. **Infraestructura exclusiva**: usar identidades/colas/DLQ y Worker diseñados para esta prueba, nunca `trendcite-nonprod-runtime` ni `trendcite-prod-runtime`. No crear recursos hasta establecer presupuesto máximo y verificar tarifas y reversibilidad.
3. **Provider proof**: validar que realmente es posible obtener atestación de muerte de Worker postcommit y evidencia de pérdida de ACK de transporte; inyectar una excepción de aplicación NO cumple estos requisitos.
4. **Run unitario controlado**: un ciclo por hipótesis, con identificadores únicos, límites/timeout, auditoría read-only independiente, limpieza de filas/colas de prueba, desmantelamiento y comprobación de costo.
5. **No cerrar criterios por documentación**: los tres claims siguen `NOT_VERIFIED` hasta disponer de trazas alojadas verificables y con alcance correcto.

## Estado

`AUTHORIZATION=APPROVED_ISOLATED_NONPROD`
`POSTGRES_PROBE=BLOCKED_UNUSABLE_LOGIN`
`WORKER_TERMINATION=BLOCKED_NO_DEDICATED_WORKER`
`BROKER_ACK_LOSS=BLOCKED_NO_DEDICATED_WORKER_QUEUE`
`HOSTED_CERTIFICATION=NOT_VERIFIED`
`PRODUCTION=DARK`
`COMMERCIALIZATION=HOLD`
`PR_121=DRAFT`

No se ha enviado tráfico, escrito datos de prueba ni alterado infraestructura alojada.
