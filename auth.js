/**
 * AI-SalesWizard — Auth wrapper (auth.js)
 * Sits between app.html and the Flask backend.
 * All API calls go through window.AISW.
 */
(function(w){
  'use strict';

  var TOKEN_KEY = 'aisw_token';
  var USER_KEY  = 'aisw_user';
  var BASE      = '';  // same origin

  // ── Token helpers ──────────────────────────────────────────
  function getToken(){ return localStorage.getItem(TOKEN_KEY) || ''; }
  function setToken(t){ localStorage.setItem(TOKEN_KEY, t); }
  function setUser(u){ localStorage.setItem(USER_KEY, JSON.stringify(u)); }
  function getUser(){
    try{ return JSON.parse(localStorage.getItem(USER_KEY)||'null'); }catch(e){ return null; }
  }
  function clearSession(){ localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); }

  // ── Fetch wrapper ───────────────────────────────────────────
  function api(method, path, body){
    var opts = {
      method: method,
      headers: { 'Content-Type': 'application/json', 'X-Auth-Token': getToken() }
    };
    if(body !== undefined){ opts.body = JSON.stringify(body); }
    return fetch(BASE + path, opts).then(function(r){ return r.json(); });
  }

  // ── requireAuth ─────────────────────────────────────────────
  // Checks token with /api/me. If valid, calls cb(user).
  // If not, redirects to login page.
  function requireAuth(cb){
    var token = getToken();
    if(!token){ w.location.href = '/'; return; }
    api('GET', '/api/me').then(function(data){
      if(data.error){
        clearSession();
        w.location.href = '/';
        return;
      }
      setUser(data);
      // Show user info in the app if elements exist
      var el = document.getElementById('aisw-user-name');
      if(el) el.textContent = data.name || data.email;
      var el2 = document.getElementById('aisw-usage-badge');
      if(el2 && data.usage){
        el2.textContent = data.usage.current + ' / ' + data.usage.cap + ' AI calls';
      }
      if(cb) cb(data);
    }).catch(function(){
      w.location.href = '/';
    });
  }

  // ── Playbook ────────────────────────────────────────────────
  function loadPlaybook(cb){
    api('GET', '/api/playbook').then(function(data){
      if(cb) cb(data.error ? null : data);
    }).catch(function(){ if(cb) cb(null); });
  }

  function savePlaybook(data){
    api('POST', '/api/playbook', data).catch(function(e){ console.warn('Playbook save failed', e); });
  }

  // ── API Keys ────────────────────────────────────────────────
  function loadKeys(cb){
    api('GET', '/api/keys').then(function(data){
      if(cb) cb(data.error ? {} : data);
    }).catch(function(){ if(cb) cb({}); });
  }

  function saveKeys(keys){
    api('POST', '/api/keys', keys).catch(function(e){ console.warn('Keys save failed', e); });
  }

  // ── Usage tracking ──────────────────────────────────────────
  // Returns a Promise<boolean> — true if allowed, false if cap hit.
  function trackUsage(){
    return api('POST', '/api/usage').then(function(data){
      if(data.error){ return false; }
      // Update badge if present
      var el = document.getElementById('aisw-usage-badge');
      if(el && data.current !== undefined){
        el.textContent = data.current + ' / ' + data.cap + ' AI calls';
        if(!data.remaining || data.remaining <= 5){
          el.style.color = '#c0392b';
        }
      }
      return true;
    }).catch(function(){ return false; });
  }

  // ── Logout ──────────────────────────────────────────────────
  function logout(){
    clearSession();
    w.location.href = '/';
  }

  // ── Change password ─────────────────────────────────────────
  function changePassword(newPw, cb){
    api('POST', '/api/change-password', { password: newPw }).then(function(data){
      if(cb) cb(!data.error, data.error || null);
    }).catch(function(e){ if(cb) cb(false, e.message); });
  }

  // ── Expose public API ────────────────────────────────────────
  w.AISW = {
    requireAuth:    requireAuth,
    loadPlaybook:   loadPlaybook,
    savePlaybook:   savePlaybook,
    loadKeys:       loadKeys,
    saveKeys:       saveKeys,
    trackUsage:     trackUsage,
    logout:         logout,
    changePassword: changePassword,
    getToken:       getToken,
    getUser:        getUser
  };

}(window));
