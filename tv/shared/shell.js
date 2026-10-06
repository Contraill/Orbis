/* The TV packages keep only a launcher; Orbis itself is served by the configured host. */
(function (root) {
  'use strict';
  var ADDRESS_KEY = 'orbis.tv.server.v1';
  var INSTALL_KEY = 'orbis.tv.installation.v1';

  function normalizeServerAddress(value) {
    var input = String(value || '').trim();
    if (!input || /[\s\\]/.test(input)) throw new Error('Enter a valid server address.');
    if (!/^https?:\/\//i.test(input)) input = 'http://' + input;
    var url;
    try { url = new URL(input); } catch (_) { throw new Error('Enter a valid server address.'); }
    if (!/^https?:$/.test(url.protocol) || !url.hostname || url.username || url.password ||
        (url.pathname && url.pathname !== '/') || url.search || url.hash) {
      throw new Error('Use a server address without a path or sign-in details.');
    }
    // A bare IP/host without a port uses the standard Orbis frontend port.
    if (!url.port && url.protocol === 'http:' && !/^https?:\/\//i.test(String(value).trim())) url.port = '3000';
    return url.origin;
  }

  function healthRequest(origin, done) {
    var xhr = new XMLHttpRequest();
    var completed = false;
    function finish(ok) { if (!completed) { completed = true; done(ok); } }
    xhr.open('GET', origin + '/api/health', true);
    xhr.timeout = 7000;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      var healthy = false;
      if (xhr.status === 200) {
        try { healthy = JSON.parse(xhr.responseText).status === 'ok'; } catch (_) { /* invalid response */ }
      }
      finish(healthy);
    };
    xhr.onerror = xhr.ontimeout = function () { finish(false); };
    try { xhr.send(); } catch (_) { finish(false); }
    return xhr;
  }

  function installationId(storage) {
    var id = storage.getItem(INSTALL_KEY);
    if (id) return id;
    var bytes = new Uint8Array(16);
    if (!root.crypto || !root.crypto.getRandomValues) return null;
    root.crypto.getRandomValues(bytes);
    id = Array.prototype.map.call(bytes, function (n) { return ('0' + n.toString(16)).slice(-2); }).join('');
    storage.setItem(INSTALL_KEY, id);
    return id;
  }

  function start(doc, storage, platform) {
    var setup = doc.getElementById('setup');
    var offline = doc.getElementById('offline');
    var checking = doc.getElementById('checking');
    var address = doc.getElementById('address');
    var error = doc.getElementById('form-error');
    var configured = doc.getElementById('configured');
    var current = storage.getItem(ADDRESS_KEY);
    var pending = null;
    var sequence = 0;
    var id = installationId(storage);
    var idLabel = doc.getElementById('installation-id');
    if (idLabel) idLabel.textContent = id || 'Unavailable';

    function screen(which) {
      setup.hidden = which !== 'setup';
      offline.hidden = which !== 'offline';
      checking.hidden = which !== 'checking';
    }
    function stopChecks() {
      sequence += 1;
      if (pending) pending.abort();
      pending = null;
    }
    function showSetupFromReturn() {
      if (!root.history || !root.history.state || !root.history.state.orbisTvLauncher) return false;
      stopChecks();
      root.history.replaceState(null, '');
      address.value = current || '';
      screen('setup');
      address.focus();
      return true;
    }
    function checkin(done) {
      if (platform !== 'webos' || !id || !current) { done(); return; }
      var xhr = new XMLHttpRequest();
      var finished = false;
      function finish() { if (!finished) { finished = true; done(); } }
      xhr.open('POST', current + '/api/tv/webos/check-in', true);
      xhr.setRequestHeader('Content-Type', 'text/plain');
      xhr.timeout = 3000;
      xhr.onreadystatechange = function () { if (xhr.readyState === 4) finish(); };
      xhr.onerror = xhr.ontimeout = finish;
      try { xhr.send(id); } catch (_) { finish(); }
    }
    function connect(origin) {
      stopChecks();
      current = origin;
      configured.textContent = origin;
      screen('checking');
      var token = sequence;
      pending = healthRequest(origin, function (ok) {
        if (token !== sequence) return;
        pending = null;
        if (!ok) {
          screen('offline');
          doc.getElementById('retry').focus();
          return;
        }
        storage.setItem(ADDRESS_KEY, origin);
        // Top-level navigation is essential: Orbis's strict session cookie
        // would not work in a cross-origin iframe inside the packaged app.
        var destination = origin + '/?orbis_tv=1&orbis_tv_back=' + encodeURIComponent(root.history.length);
        root.history.replaceState({ orbisTvLauncher: true }, '');
        checkin(function () { root.location.assign(destination); });
      });
    }
    doc.getElementById('server-form').addEventListener('submit', function (event) {
      event.preventDefault();
      try { error.textContent = ''; connect(normalizeServerAddress(address.value)); }
      catch (problem) { error.textContent = problem.message; address.focus(); }
    });
    doc.getElementById('retry').addEventListener('click', function () { if (current) connect(current); });
    doc.getElementById('change-server').addEventListener('click', function () {
      stopChecks();
      address.value = current || '';
      screen('setup');
      address.focus();
    });
    // Only local launcher screens consume Back. The loaded product owns navigation.
    doc.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' || event.key === 'Backspace' || event.keyCode === 461 || event.keyCode === 10009) {
        event.preventDefault();
        if (!offline.hidden) doc.getElementById('retry').focus();
      }
    });
    if (root.addEventListener) root.addEventListener('pageshow', showSetupFromReturn);
    if (showSetupFromReturn()) return { connect: connect, stop: stopChecks };
    if (current) {
      try { connect(normalizeServerAddress(current)); }
      catch (_) { storage.removeItem(ADDRESS_KEY); screen('setup'); address.focus(); }
    } else { screen('setup'); address.focus(); }
    return { connect: connect, stop: stopChecks };
  }

  var api = { normalizeServerAddress: normalizeServerAddress, healthRequest: healthRequest, start: start };
  root.OrbisTvShell = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
