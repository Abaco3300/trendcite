import test from "node:test";
import assert from "node:assert/strict";
import {handleFaultMessage, recordDurableCommit} from "../deploy/cloudflare/tc_p008_fault_worker.mjs";

const RUN_ID = "123e4567-e89b-42d3-a456-426614174000";
function environment() {
  const calls = [];
  const db = {
    prepare(sql) {
      calls.push(["prepare", sql]);
      return {
        bind(...args) {
          calls.push(["bind", ...args]);
          return {async run() { calls.push(["run"]); return {success: true, meta: {changes: 1}}; }};
        },
      };
    },
  };
  return {calls, env: {TC_P008_FAULT_SANDBOX: "isolated-dark",
    TC_P008_D1_NAME: "trendcite-tcp008-fault-d1", FAULT_DB: db}};
}
test("commit completes before fault-hook invocation", async () => {
  const {calls, env} = environment();
  await handleFaultMessage(env, {run_id: RUN_ID}, {afterCommit: () => {
    assert.equal(calls.at(-1)[0], "run");
  }});
});
test("fail closed on shared or missing binding", async () => {
  for (const bad of [{}, {TC_P008_FAULT_SANDBOX:"isolated-dark"},
    {TC_P008_FAULT_SANDBOX:"production", TC_P008_D1_NAME:"trendcite-tcp008-fault-d1", FAULT_DB:{prepare(){}}}]) {
    await assert.rejects(recordDurableCommit(bad, RUN_ID), /ISOLATED_ENVIRONMENT_REQUIRED/);
  }
});
test("reject invalid run identifiers before any SQL", async () => {
  const {calls, env} = environment();
  await assert.rejects(recordDurableCommit(env, "injection'--"), /INVALID_RUN_ID/);
  assert.equal(calls.length, 0);
});
test("duplicate write is not counted as newly inserted", async () => {
  const {env} = environment();
  env.FAULT_DB.prepare = () => ({bind: () => ({run: async () => ({success:true, meta:{changes:0}})})});
  const result = await recordDurableCommit(env, RUN_ID);
  assert.equal(result.committed, true);
  assert.equal(result.newlyInserted, false);
});
test("duplicate delivery never triggers the provider fault hook", async () => {
  const {env} = environment();
  env.FAULT_DB.prepare = () => ({bind: () => ({run: async () => ({success:true, meta:{changes:0}})})});
  let faults = 0;
  const result = await handleFaultMessage(env, {run_id: RUN_ID}, {afterCommit: () => { faults++; }});
  assert.equal(result.newlyInserted, false);
  assert.equal(faults, 0);
});
test("reject D1 write without a countable outcome", async () => {
  const {env} = environment();
  env.FAULT_DB.prepare = () => ({bind: () => ({run: async () => ({success:true})})});
  await assert.rejects(recordDurableCommit(env, RUN_ID), /DURABLE_COMMIT_UNCONFIRMED/);
});
test("reject unconfirmed D1 write", async () => {
  const {env} = environment();
  env.FAULT_DB.prepare = () => ({bind: () => ({run: async () => ({success:false})})});
  await assert.rejects(recordDurableCommit(env, RUN_ID), /DURABLE_COMMIT_UNCONFIRMED/);
});
