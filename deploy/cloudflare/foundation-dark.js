export default {
  async fetch() {
    return new Response(JSON.stringify({ ok: false, error: "not_found" }), {
      status: 404,
      headers: { "content-type": "application/json" },
    });
  },

  async scheduled() {
    return;
  },

  async queue() {
    throw new Error("production foundation is dark");
  },
};
