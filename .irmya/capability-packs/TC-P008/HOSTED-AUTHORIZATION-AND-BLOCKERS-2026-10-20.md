# TC-P008 — Autorización y bloqueo de ejecución alojada (2026-10-20)

## Alcance autorizado
Autorización del operador para tres pruebas exclusivamente en NONPROD aislado: (1) contención de INSERT en clave única con dos transacciones independientes; (2) terminación **real** de Worker después de commit; (3) pérdida **real** de ACK de transporte y recuperación por broker. Sin producción, clientes, pagos ni comercialización. No usar la infraestructura compartida.

## Comprobación real de precondiciones (solo lectura)
- GitHub PR #121, HEAD inicial `86f8656f677ad433973145619a2ba94f27a6c7c8`: CI SUCCESS, PR DRAFT.
- Supabase proyecto **exclusivo** `btjgozzguhuzfdueensf` (`trendcite-tcp008-sandbox`): `ACTIVE_HEALTHY`.
- Consulta de catálogo `pg_authid`, sin recuperar secretos: `tc_p008_probe_login` tiene LOGIN, contraseña AUSENTE, `rolvaliduntil=2026-10-18 23:59:00+00`. No tiene SUPERUSER, CREATEDB, CREATEROLE ni BYPASSRLS.
- Como la cuenta no puede autenticarse, no se realizó ninguna conexión de prueba con dicha cuenta, INSERT concurrente, DELETE ni cancelación de sesiones.
- La conexión de administración del conector Supabase no sirve para certificar dos sesiones separadas con la identidad restringida.
- No se ejecutó inyección de caída de Worker ni interferencia en ACK, ni se tocó Cloudflare.
- Ningún importe externo fue aprobado explícitamente. No crear recursos facturables ni iniciar pruebas con costes no acotados.

## Criterios de reanudación — una ejecución agrupada
1. Operador provisiona/rota una credencial **temporal**, vigente y protegida en un canal nativo de proveedor, sin mostrarla al chat, terminal, GitHub o logs; comprobar rol, permisos, endpoint TLS, revocación y expiración.
2. Confirmar rutas y recursos NONPROD **independientes** (Worker, Queue, DLQ, base de datos) y observabilidad del proveedor; no reutilizar runtime común.
3. Establecer un tope de gasto explícito y verificable antes de crear recursos o generar tráfico susceptible de coste.
4. Ejecutar pruebas una sola vez, con límites de concurrencia y duración, marcadores únicos, trazas de proveedor, verificación independiente y recuperación.
5. Tras cada prueba: comprobar cero residuo únicamente en ámbito sintético; desactivar hooks, revocar credenciales, verificar colas/bindings y mantener DARK/HOLD.
6. Solo evidencia real permite actualizar la matriz de aceptación; fallo/no evidencia queda NOT_VERIFIED y la PR sigue DRAFT.

## Estado
`HOSTED_UNIQUE_KEY=BLOCKED_CREDENTIAL`
`HOSTED_WORKER_TERMINATION=NOT_RUN_RESOURCE_AND_COST_PREFLIGHT`
`HOSTED_TRANSPORT_ACK_LOSS=NOT_RUN_RESOURCE_AND_COST_PREFLIGHT`
`HOSTED_CERTIFICATION=NOT_VERIFIED`
`PRODUCTION=DARK`
`COMMERCIALIZATION=HOLD`
`PR_121=DRAFT`
