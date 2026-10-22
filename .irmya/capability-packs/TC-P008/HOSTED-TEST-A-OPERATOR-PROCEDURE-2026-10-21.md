# TC-P008 — Ejecución alojada 2026-10-21: runner habilitado, gates restantes y procedimiento de Test A

## 1. Comprobaciones reales de esta intervención

- Gobernanza cargada desde fuente canónica: `GLOBAL-INSTRUCTIONS.md` v1.16.0, Execution Handoff Contract v1.0.0, CI/CD Policy v2.0.0, Shared Infrastructure v1.5.0; IRMYA `CURRENT_STATE.md` (`master`, OUTCOME_DRIVEN_AUTONOMOUS).
- PR #121 al inicio: HEAD `f05d098b9aff88752800ecd4dfc2f66c1b3625cc`, DRAFT, check `Preflight (Python 3.11)` SUCCESS (run `39522853673`).
- Preflight canónico local en venv Python 3.11 aislado, importando `trendcite` desde el árbol de trabajo verificado: PASS (línea base y tras los cambios).
- Supabase `trendcite-tcp008-sandbox` (`btjgozzguhuzfdueensf`), organización `ISTRIADE Development` en plan **Free** (consumo de ciclo: egress 0/5 GB). Consulta de catálogo **solo lectura** (2026-10-22T00:45:52Z): `tc_p008_probe_login` LOGIN, sin SUPERUSER/CREATEROLE/CREATEDB/BYPASSRLS, `password_configured=false`, `valid_until=2026-10-18T23:59:00Z`, miembro de `tc_p008_probe_writer`, USAGE de esquema, INSERT/SELECT/DELETE sí, UPDATE no, CREATE de esquema no; `residual_rows=0`; `active_sessions=0`; PostgreSQL 17.11; `password_encryption=scram-sha-256`; **`log_statement=ddl`**. `postgres` tiene ADMIN OPTION sobre el rol (puede renovar contraseña y vigencia).
- Endpoint de pooler de sesión mostrado por el proveedor: `aws-0-us-east-1.pooler.supabase.com:5432` (el directo es solo IPv6 en plan Free).

## 2. Por qué la credencial no se configuró desde esta sesión

- `log_statement=ddl`: un `ALTER ROLE ... PASSWORD '<texto>'` desde el editor SQL o cualquier conector dejaría la contraseña en los logs de Postgres y en el historial del editor. Queda prohibido.
- El conector Supabase de esta sesión no tiene permiso sobre esta organización y el entorno de ejecución en la nube no resuelve ni alcanza el host PostgreSQL (sin DNS/TCP 5432). Ninguna sesión restringida puede abrirse desde aquí.
- Se descartó generar la credencial con una Edge Function usando la conexión administrativa: sería un procedimiento improvisado de custodia de secretos con credenciales de administrador.
- **Canal nativo protegido identificado:** `psql \password` (calcula el verificador SCRAM en el cliente; el texto plano nunca llega al SQL ni a los logs; solo el verificador queda registrado por `log_statement=ddl`) + `VALID UNTIL` corto + autorrevocación por el propio runner (`ALTER ROLE CURRENT_USER PASSWORD NULL`).

## 3. Defectos corregidos (rama `irmya/tc-p008-hosted-runner-implementation`)

1. **Dependencia de empaquetado:** `trendcite.cloud.tc_p008_connection_policy` importaba `scripts.tc_p008_hosted_preflight`, que no se empaqueta. La wheel instalada fallaba con `ModuleNotFoundError: No module named 'scripts'` (reproducido sobre `f05d098`). La lista de destinos permitidos pasa a `trendcite.cloud.tc_p008_sandbox_target`; un test bloquea cualquier reintroducción de imports desde `scripts` en el runtime.
2. **TLS inutilizable:** `sslmode=verify-full` sin `sslrootcert`; los endpoints Supabase usan su propia CA raíz, no pública, por lo que la conexión fallaría siempre. Ahora la CA es obligatoria en la CLI y se valida como PEM legible antes de cualquier conexión.
3. **Sin ruta IPv4:** solo se permitía el host directo (solo IPv6). Se añade el pooler de **sesión** (backend dedicado por cliente, evidencia de dos sesiones válida); el modo transacción (6543) sigue prohibido. No se envía `options` al pooler; el rol ya fija los mismos timeouts y el runner los repite con `SET LOCAL`.
4. **Verificación de terminación de backends:** una lectura única de `pg_stat_activity` justo después de cerrar sockets da falsos "activos" y además el estado se cachea por transacción. Ahora hay un sondeo acotado (10 × 0,2 s) con `pg_stat_clear_snapshot()` antes de cada lectura.
5. **Runner que nunca devolvía evidencia:** el flujo terminaba con `assess_hosted_probe(hosted_run_attested=False)`, que siempre lanzaba excepción *después* de limpiar, así que la evidencia de una ejecución real se perdía. Ahora devuelve evidencia sin secretos con los contratos de contención y limpieza, siempre con `hosted_certification=NOT_VERIFIED_PENDING_INDEPENDENT_REVIEW`. La certificación sigue requiriendo `assess_hosted_probe(..., hosted_run_attested=True)` por un revisor independiente.
6. **`execute_probe`** solo se ejecuta con `approved=True` y una factoría invocable; el bloqueo obsoleto ("independent cleanup audit not implemented") se elimina porque `independently_audit_cleanup` ya existe y está probado.
7. **CLI de operador** `scripts/tc_p008_hosted_unique_key_probe.py`: contraseña solo por `getpass` (nunca argv/env/logs), confirmación literal, verificación de identidad restringida + TLS + mínimo privilegio, ejecución única, autorrevocación en `finally` y salida JSON sin secretos.

## 4. Pruebas B y C — evaluación técnica (sin aprovisionar)

- **Sin credenciales Cloudflare en esta sesión** (ni API token ni conector). No se pudo reverificar el inventario y no se creó ningún recurso.
- **B (terminación real del Worker):** técnicamente demostrable. El runtime termina la invocación por límite de memoria/CPU y lo registra como resultado del proveedor ("Exceeded Memory"/"Exceeded CPU" en métricas, Workers Logs y Trace Events). Pero exige un **commit persistente** desde el Worker: Postgres del sandbox (Hyperdrive o socket con la misma credencial temporal → mismo gate) o un D1 exclusivo (recurso fuera del manifiesto aprobado). El manifiesto `tc_p008_fault_isolation_manifest.json` no admite hoy ningún binding de persistencia. Estado: **BLOCKED_CREDENTIAL_OR_SCOPE**, no aprovisionado para no crear recursos inútiles.
- **C (pérdida real de ACK en transporte):** en consumidores push el ACK es interno entre runtime y Queues, sin transporte observable. En consumidores pull el ACK es un `POST /messages/ack` con `lease_id`; si no llega, el mensaje se reentrega al vencer el visibility timeout. La documentación del proveedor no ofrece registro, recibo ni traza de peticiones ACK recibidas o perdidas, y el egreso de este entorno pasa por un proxy que termina TLS. Por eso una reentrega no distingue entre "ACK perdido en transporte" y "ACK no enviado". **Estado: NOT_VERIFIED**: el proveedor no permite atribuir la pérdida al transporte. No se rebaja el criterio.

## 5. Procedimiento del operador — Test A (intervención humana mínima)

Punto de partida: `LAPTOP-JOSEMILE`, PowerShell, carpeta `C:\Users\angel\Projects\trendcite-tcp008-20261017`. No tocar `ISTRIADE PLATFORM`, colas o Workers de Cloudflare, ni el resto de roles.

1. **Actualizar el código:** `git fetch origin` y luego `git checkout irmya/tc-p008-hosted-runner-implementation` y `git pull --ff-only`. Resultado esperado: HEAD = commit final de este checkpoint (ver PR #121).
2. **Entorno:** `py -3.11 -m venv .venv-tcp008` → `.\.venv-tcp008\Scripts\Activate.ps1` → `pip install -e . "psycopg[binary]>=3.2"`. Comprobar con `python -c "import trendcite;print(trendcite.__file__)"` que la ruta está dentro de esta carpeta.
3. **CA del proveedor (no es secreta):** en supabase.com/dashboard → proyecto `trendcite-tcp008-sandbox` → Project Settings → Database → *SSL Configuration* → **Download certificate**. Guardarla como `C:\Users\angel\supabase-ca\prod-ca-2021.crt`. No se sube a Git.
4. **Elegir el transporte:** `Test-NetConnection db.btjgozzguhuzfdueensf.supabase.co -Port 5432`. Si `TcpTestSucceeded : True` → `direct`. Si no → `session-pooler`.
5. **Credencial temporal (canal nativo):** generar en el gestor de contraseñas una contraseña aleatoria de 32 o más caracteres. Conectar como administrador; psql pedirá la contraseña de `postgres` sin mostrarla:
   `psql "host=aws-0-us-east-1.pooler.supabase.com port=5432 dbname=postgres user=postgres.btjgozzguhuzfdueensf sslmode=verify-full sslrootcert=C:\Users\angel\supabase-ca\prod-ca-2021.crt"`
   Dentro de psql:
   - `\password tc_p008_probe_login` (pegar la contraseña temporal dos veces; no se muestra)
   - `DO $$ BEGIN EXECUTE format('ALTER ROLE tc_p008_probe_login VALID UNTIL %L', (now() + interval '2 hours')::text); END $$;`
   - Verificación: `SELECT rolvaliduntil, (SELECT rolpassword IS NOT NULL FROM pg_authid WHERE rolname='tc_p008_probe_login') AS pw FROM pg_roles WHERE rolname='tc_p008_probe_login';` → `pw = t`, vigencia de unas 2 h.
   - **No usar** el editor SQL del dashboard ni escribir `PASSWORD '...'`, porque `log_statement=ddl` lo registraría.
6. **Ejecutar una sola vez:**
   `python scripts\tc_p008_hosted_unique_key_probe.py --transport <direct|session-pooler> --sslrootcert C:\Users\angel\supabase-ca\prod-ca-2021.crt --evidence-out ..\tc-p008-testA-evidence.json --confirm RUN-TC-P008-TEST-A-ONCE`
   Pegar la contraseña temporal cuando la pida (no se ve). Resultado esperado: código 0, `probe_status=COMPLETED_EVIDENCE_PENDING_REVIEW`, `credential_revocation=PASSWORD_NULL_COMMITTED`, `winner=holder`, `durable_count=1`, `contender_insert_count=0`, `blocking_pid` igual a `holder_pid`, `independent_audit_remaining_rows=0`.
7. **Cierre obligatorio, aunque falle:** en la sesión psql de administrador:
   `ALTER ROLE tc_p008_probe_login PASSWORD NULL VALID UNTIL '2000-01-01 00:00:00+00';`
   Verificación: `SELECT (SELECT count(*) FROM tc_p008_isolated.unique_write_probe) AS filas, (SELECT count(*) FROM pg_stat_activity WHERE usename='tc_p008_probe_login') AS sesiones, (SELECT rolpassword IS NULL FROM pg_authid WHERE rolname='tc_p008_probe_login') AS sin_password;` → `0 | 0 | t`. Después `\q`. Borrar la contraseña temporal del gestor.
8. **Entregar** `tc-p008-testA-evidence.json` (no contiene secretos) al ejecutor para la revisión independiente y la actualización de la matriz.

Coste: plan Free de Supabase, sin recursos nuevos → USD 0 previsto.

## 6. Estado

`HOSTED_UNIQUE_KEY=READY_FOR_OPERATOR_RUN / BLOCKED_HUMAN_CREDENTIAL_ENTRY`
`HOSTED_WORKER_TERMINATION=BLOCKED_CREDENTIAL_OR_SCOPE / NO_CLOUDFLARE_ACCESS_THIS_SESSION`
`HOSTED_TRANSPORT_ACK_LOSS=NOT_VERIFIED (provider cannot attest transport loss)`
`TC_P008_NONPROD_TEST_BUDGET_SPENT_USD=0.00 (no billable resource or traffic created)`
`HOSTED_CERTIFICATION=NOT_VERIFIED`
`PRODUCTION=DARK`
`COMMERCIALIZATION=HOLD`
`PR_121=DRAFT`

## 7. Actualización de continuidad — 2026-10-22 (posterior a `5524731`)

- El repositorio del operador se sincronizó por fast-forward con `707e73e`, y se publicó después `5524731` en la PR #121, que permanece **DRAFT**.
- Corrección de seguridad en `5524731`: el CLI no serializa textos arbitrarios de excepciones del driver. Ante un fallo del probe, `probe_error=PROBE_EXCEPTION_REDACTED`; una prueba con un secreto sintético verifica que no aparece en JSON. Batería `python -m pytest -q` en Python 3.13.14: PASS (exit 0), y regresiones específicas: PASS. **La CI remota para ese commit no está confirmada**; no equiparar a certificación alojada.
- El operador dispone de `psql` 17.11 en `C:\Program Files\PostgreSQL\17\bin\psql.exe`, Python 3.13.14 y psycopg 3.3.6. El import del CLI debe resolver `trendcite` desde el `src` de este repositorio (por ejemplo usando un entorno virtual con instalación editable), no desde otra instalación homónima. La validación local con 3.13 no sustituye la validación canónica con Python 3.11.
- Se encontró en el equipo el archivo `C:\Users\angel\supabase-ca\prod-ca-2021.crt`; sus tres copias en Descargas tenían igual SHA-256. Una conexión `psql` a `aws-0-us-east-1.pooler.supabase.com:5432` con `sslmode=verify-full` y `sslrootcert=C:/Users/angel/supabase-ca/prod-ca-2021.crt` llegó a autenticación y terminó en `fe_sendauth: no password supplied`, sin enviar contraseña. **Sigue pendiente confirmar independientemente la procedencia de la CA desde el panel del proyecto.** En la cadena de conexión `libpq`, utilizar barras `/` en `sslrootcert` para evitar interpretación de escapes con rutas Windows.
- Supabase `tc_p008_probe_login` seguía sin contraseña y con `VALID UNTIL` caducado en comprobación de solo lectura. No se ha restablecido la contraseña de administrador ni generado una credencial temporal. Mantener el gate: `psql \password`, vigencia corta, una ejecución y revocación obligatoria.
- El conector de Cloudflare **sí** respondió posteriormente y permitió comprobar por lectura que existen `trendcite-nonprod-runtime` y `trendcite-prod-runtime`, sin D1 exclusivo ni Worker exclusivo TC-P008. Esto **no** autoriza experimentar sobre Workers/Queues compartidos; B continúa bloqueada por aislamiento y persistencia. C continúa NOT_VERIFIED por ausencia de prueba independiente de pérdida real del ACK.
- Mantener las afirmaciones originales de 2026-10-21 como histórico de su sesión; este anexo prevalece donde exista contradicción. Sin activación de producción ni comercialización; `HOSTED_CERTIFICATION=NOT_VERIFIED`, `PRODUCTION=DARK`, `COMMERCIALIZATION=HOLD`.
