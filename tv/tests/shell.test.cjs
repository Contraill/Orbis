const assert = require('node:assert/strict');
const test = require('node:test');
const shell = require('../shared/shell.js');

test('normalizes bare, ported and HTTPS server addresses', () => {
  assert.equal(shell.normalizeServerAddress('100.90.80.70'), 'http://100.90.80.70:3000');
  assert.equal(shell.normalizeServerAddress('100.90.80.70:3000'), 'http://100.90.80.70:3000');
  assert.equal(shell.normalizeServerAddress('http://100.90.80.70:3000'), 'http://100.90.80.70:3000');
  assert.equal(shell.normalizeServerAddress('https://orbis.example.com'), 'https://orbis.example.com');
  for (const bad of ['ftp://server', 'http://user:secret@server', 'server/path', 'server?token=1', '']) {
    assert.throws(() => shell.normalizeServerAddress(bad));
  }
});

function harness(results, platform = 'tizen') {
  const elements = {};
  for (const name of ['setup', 'offline', 'checking', 'address', 'form-error', 'configured', 'installation-id', 'server-form', 'retry', 'change-server']) {
    elements[name] = { hidden: true, value: '', textContent: '', listeners: {}, focus() { this.focused = true; }, addEventListener(event, callback) { this.listeners[event] = callback; } };
  }
  const listeners = {};
  const doc = { hidden: false, getElementById: (id) => elements[id], addEventListener: (event, callback) => { listeners[event] = callback; } };
  const data = new Map();
  const storage = { getItem: (key) => data.get(key) || null, setItem: (key, value) => data.set(key, value), removeItem: (key) => data.delete(key) };
  const navigations = [];
  global.location = { assign: (url) => navigations.push(url) };
  global.history = { length: 1, state: null, replaceState(value) { this.state = value; } };
  global.XMLHttpRequest = class {
    open(method, url) { this.method = method; this.url = url; }
    setRequestHeader() {}
    send() {
      const next = results.shift() || { status: 0 };
      setTimeout(() => { this.status = next.status; this.responseText = next.body || '';
        this.readyState = 4; this.onreadystatechange?.(); }, 0);
    }
    abort() {}
  };
  shell.start(doc, storage, platform);
  return { elements, storage, navigations, platform };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 10));
test('first-run preflight, persistence and full-page live frontend navigation', async () => {
  const h = harness([{ status: 200, body: '{"status":"ok"}' }]);
  assert.equal(h.elements.setup.hidden, false);
  h.elements.address.value = '100.90.80.70';
  h.elements['server-form'].listeners.submit({ preventDefault() {} });
  await tick();
  assert.equal(h.storage.getItem('orbis.tv.server.v1'), 'http://100.90.80.70:3000');
  assert.equal(h.navigations[0], 'http://100.90.80.70:3000/?orbis_tv=1&orbis_tv_back=1');
});

test('unreachable server displays local retry and change-server screens', async () => {
  const h = harness([{ status: 0 }, { status: 0 }]);
  h.elements.address.value = 'https://orbis.example.com';
  h.elements['server-form'].listeners.submit({ preventDefault() {} });
  await tick();
  assert.equal(h.elements.offline.hidden, false);
  assert.equal(h.elements.configured.textContent, 'https://orbis.example.com');
  h.elements.retry.listeners.click();
  await tick();
  assert.equal(h.elements.offline.hidden, false);
  h.elements['change-server'].listeners.click();
  assert.equal(h.elements.setup.hidden, false);
  assert.equal(h.elements.address.value, 'https://orbis.example.com');
});
