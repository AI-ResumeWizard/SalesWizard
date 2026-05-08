# AI-SalesWizard — Deployment Guide

## Files
- `server.py` — Flask backend (auth, playbook storage, usage tracking, admin API)
- `static/login.html` — Login/register page (serves as `/`)
- `static/admin.html` — Admin panel (serves as `/admin`)
- `static/auth.js` — Auth wrapper for the main app
- `static/app.html` — Main playbook builder (copy aisaleswizard-v4.html here, rename to app.html)
- `requirements.txt` — Flask + gunicorn
- `render.yaml` — Render.com deployment config

## Deploy to Render.com

1. Create a new GitHub repo
2. Push all files to it
3. Connect repo to Render.com → New Web Service
4. Set environment variables:
   - `ADMIN_EMAIL` = your email (e.g. michael@weinstein.tech)
   - `ADMIN_PASSWORD` = your admin password (keep this secret)
   - `SECRET` = any random string (used for token generation)
5. Add a Persistent Disk: mount at `/opt/data`, 1GB
6. Deploy

## Integrating the Playbook Builder (app.html)

Take your `aisaleswizard-v4.html` file, rename it `app.html`, and place it in `static/`.

Then add these changes to app.html:

### 1. Add auth.js before your closing </body>
```html
<script src="/auth.js"></script>
```

### 2. Replace DOMContentLoaded with auth-aware version
```javascript
window.addEventListener('DOMContentLoaded', function(){
  AISW.requireAuth(function(user){
    // Load playbook from server instead of localStorage
    AISW.loadPlaybook(function(pb){
      if(pb && pb.rep) { S.rep = pb.rep; S.products = pb.products || []; }
      AISW.loadKeys(function(keys){
        if(keys.gemini) document.getElementById('gemini-apikey').value = keys.gemini;
        if(keys.anthropic) document.getElementById('rep-apikey').value = keys.anthropic;
        if(keys.groq) document.getElementById('groq-apikey').value = keys.groq;
        if(keys.serper) document.getElementById('serper-apikey').value = keys.serper;
        if(keys.openai) document.getElementById('openai-apikey').value = keys.openai;
      });
      restoreRepForm();
      ['rep-ind','pm-lang','pd-ind','pd-trig','pd-roi'].forEach(initTag);
      renderSidebar(); renderOverview(); updateBadge(); updateComp();
      setChatCtx('rep');
      loadApiKey();
    });
  });
});
```

### 3. Replace persist() to save to server
```javascript
function persist(){
  var data = {rep: S.rep, products: S.products};
  AISW.savePlaybook(data);
  // Keep localStorage as offline cache
  try{ localStorage.setItem('aisw4', JSON.stringify(S)); }catch(e){}
}
```

### 4. Replace saveApiKey() to save keys to server
```javascript
function saveApiKey(){
  var keys = {
    gemini: document.getElementById('gemini-apikey').value.trim(),
    anthropic: document.getElementById('rep-apikey').value.trim(),
    groq: document.getElementById('groq-apikey').value.trim(),
    openai: document.getElementById('openai-apikey').value.trim(),
    serper: document.getElementById('serper-apikey').value.trim()
  };
  AISW.saveKeys(keys);
  // Also cache locally
  Object.entries(keys).forEach(([k,v]) => { if(v) localStorage.setItem('aisw4_'+k+'key', v); });
}
```

### 5. Add usage tracking to AI calls
In `callGeminiRaw`, before making the API call:
```javascript
var allowed = await AISW.trackUsage();
if(!allowed) throw new Error('AI credit limit reached');
```

## Default Admin Credentials
- Email: set via ADMIN_EMAIL env var
- Password: set via ADMIN_PASSWORD env var
- URL: yourdomain.com/admin

## User Flow
1. Admin creates company workspaces at /admin → Companies
2. Admin builds product playbooks using the main app (?company=name)
3. Admin registers users at /admin → Users → Register User
4. Admin pre-loads a template playbook for the user
5. Admin sends user their email + temp password
6. User logs in at yourdomain.com, changes their password, edits their playbook

## Usage Caps
- Self-registered users: 50 AI calls (adjustable by admin)
- Admin-registered users: set at registration (default 100)
- Admin: unlimited
- Caps are lifetime totals — every AI Coach message, Auto-Fill, and Suggest call counts as 1
