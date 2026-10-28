// TC-P008 isolated NONPROD fault probe. Never deployed by CI.
const REQUIRED_SANDBOX = "isolated-dark";
const REQUIRED_DATABASE = "trendcite-tcp008-fault-d1";
const KEY_PATTERN = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;

export function validateFaultEnvironment(env) {
  if (env?.TC_P008_FAULT_SANDBOX !== REQUIRED_SANDBOX ||
      env?.TC_P008_D1_NAME !== REQUIRED_DATABASE ||
      typeof env?.FAULT_DB?.prepare !== "function") {
    throw new Error("TC_P008_ISOLATED_ENVIRONMENT_REQUIRED");
  }
}

export async function recordDurableCommit(env, runId) {
  validateFaultEnvironment(env);
  if (typeof runId !== "string" || !KEY_PATTERN.test(runId)) {
    throw new Error("TC_P008_INVALID_RUN_ID");
  }
  const statement = env.FAULT_DB.prepare(
    "INSERT OR IGNORE INTO tc_p008_fault_commits (run_id, phase) VALUES (?, 'committed')"
  );
  const result = await statement.bind(runId).run();
  if (!result?.success || ![0, 1].includes(result?.meta?.changes)) {
    throw new Error("TC_P008_DURABLE_COMMIT_UNCONFIRMED");
  }
  // A duplicate attempt is not another committed write. Independent D1
  // readback remains mandatory for any hosted evidence.
  return {runId, committed: true, newlyInserted: result.meta.changes === 1};
}

// Injected afterCommit is reserved for an independently authorized provider-fault
// harness. No exception, timeout or ordinary retry is evidence of a Worker kill.
export async function handleFaultMessage(env, body, {afterCommit} = {}) {
  const runId = body?.run_id;
  const committed = await recordDurableCommit(env, runId);
  // A replay must never trigger a second provider-fault experiment.
  if (committed.newlyInserted && typeof afterCommit === "function") {
    await afterCommit(committed);
  }
  return committed;
}

export default {
  async queue(batch, env) {
    validateFaultEnvironment(env);
    // The configured isolated queue is explicitly single-message.
    if (!Array.isArray(batch?.messages) || batch.messages.length !== 1) {
      throw new Error("TC_P008_SINGLE_MESSAGE_ONLY");
    }
    await handleFaultMessage(env, batch.messages[0].body);
    // A normal return is NOT Test B: no provider termination was induced.
  },
  async fetch() {
    return new Response("TC_P008_DARK", {status: 404});
  },
};
