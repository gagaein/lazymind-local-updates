const assert = require("node:assert/strict");
const test = require("node:test");

const { installNotificationSessionSync } = require("./preload");

function fixture(raw) {
  const listeners = new Map();
  const storage = new Map();
  if (raw !== undefined) storage.set("lazymind:user", raw);
  const target = {
    document: { readyState: "complete" },
    location: { origin: "http://127.0.0.1:8094" },
    localStorage: { getItem: key => storage.get(key) ?? null },
    addEventListener: (name, listener) => listeners.set(name, listener),
    removeEventListener: name => listeners.delete(name),
  };
  const calls = [];
  const bridge = {
    assistantSessionSet: value => calls.push(["set", value]),
    assistantSessionClear: () => calls.push(["clear"]),
  };
  return { target, bridge, calls, storage, listeners };
}

test("passive session sync never clears credentials for absent browser state", () => {
  for (const raw of [undefined, "invalid-json", JSON.stringify({ token: "access" })]) {
    const state = fixture(raw);
    const dispose = installNotificationSessionSync(state.target, state.bridge);
    assert.deepEqual(state.calls, []);
    dispose();
  }
});

test("passive session sync writes complete credentials and retries after an empty state", () => {
  const state = fixture(undefined);
  const dispose = installNotificationSessionSync(state.target, state.bridge);
  state.storage.set("lazymind:user", JSON.stringify({ token: "access", refreshToken: "refresh" }));
  state.listeners.get("storage")();
  assert.equal(state.calls.length, 1);
  assert.equal(state.calls[0][0], "set");
  assert.equal(state.calls[0][1].access_token, "access");
  assert.equal(state.calls[0][1].refresh_token, "refresh");
  dispose();
});
