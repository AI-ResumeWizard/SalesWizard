"""
AI-SalesWizard — Flask Backend
Multi-user auth, playbook storage, usage tracking, admin panel
"""

import os, json, hashlib, secrets, time
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, abort
from functools import wraps

app = Flask(__name__, static_folder='static', template_folder='templates')

# ── Paths ──
BASE_DIR   = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(__file__), 'data'))
USERS_DIR  = os.path.join(BASE_DIR, 'users')
COMP_DIR   = os.path.join(BASE_DIR, 'companies')
ADMIN_FILE = os.path.join(BASE_DIR, 'admin.json')

for d in [BASE_DIR, USERS_DIR, COMP_DIR]:
    os.makedirs(d, exist_ok=True)

# ── Helpers ──
def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def make_token(email):
    return hashlib.sha256(f"{email}:{os.environ.get('SECRET','aisw-secret')}".encode()).hexdigest()

def read_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except Exception:
        pass
    return default if default is not None else {}

def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def user_dir(email):
    safe = email.replace('@','_at_').replace('.','_')
    return os.path.join(USERS_DIR, safe)

def user_file(email, name):
    return os.path.join(user_dir(email), name)

# ── Admin bootstrap ──
def get_admin():
    data = read_json(ADMIN_FILE)
    if not data:
        # First run — create default admin
        pw = os.environ.get('ADMIN_PASSWORD', 'admin123')
        data = {
            'email': os.environ.get('ADMIN_EMAIL', 'admin@aisaleswizard.com'),
            'password_hash': hash_password(pw),
            'token': make_token('admin'),
            'created_at': datetime.utcnow().isoformat()
        }
        write_json(ADMIN_FILE, data)
    return data

# ── Auth decorators ──
def require_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Auth-Token', '')
        if not token:
            return jsonify({'error': 'Unauthorized'}), 401
        # Check admin token
        admin = get_admin()
        if token == admin.get('token'):
            request.current_user = {'email': admin['email'], 'is_admin': True}
            return f(*args, **kwargs)
        # Check user tokens
        email = find_user_by_token(token)
        if email:
            profile = read_json(user_file(email, 'profile.json'))
            if profile.get('status') == 'active':
                request.current_user = {**profile, 'email': email, 'is_admin': False}
                return f(*args, **kwargs)
        return jsonify({'error': 'Unauthorized'}), 401
    return decorated

def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Auth-Token', '')
        admin = get_admin()
        if token != admin.get('token'):
            return jsonify({'error': 'Admin access required'}), 403
        request.current_user = {'email': admin['email'], 'is_admin': True}
        return f(*args, **kwargs)
    return decorated

def find_user_by_token(token):
    for dirname in os.listdir(USERS_DIR):
        profile_path = os.path.join(USERS_DIR, dirname, 'profile.json')
        profile = read_json(profile_path)
        if profile.get('token') == token:
            return profile.get('email')
    return None

# ── Usage tracking ──
def check_usage(email):
    """Returns (allowed, current, cap)"""
    usage = read_json(user_file(email, 'usage.json'), {'count': 0, 'cap': 100})
    current = usage.get('count', 0)
    cap = usage.get('cap', 100)
    return current < cap, current, cap

def increment_usage(email):
    path = user_file(email, 'usage.json')
    usage = read_json(path, {'count': 0, 'cap': 100, 'history': []})
    usage['count'] = usage.get('count', 0) + 1
    usage.setdefault('history', []).append({
        'at': datetime.utcnow().isoformat(),
        'count': usage['count']
    })
    # Keep history to last 100
    usage['history'] = usage['history'][-100:]
    write_json(path, usage)
    return usage['count'], usage.get('cap', 100)

# ══════════════════════════════════════
# AUTH ROUTES
# ══════════════════════════════════════

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password', '')

    # Check admin
    admin = get_admin()
    if email == admin['email'].lower() and hash_password(password) == admin['password_hash']:
        return jsonify({
            'token': admin['token'],
            'email': admin['email'],
            'name': 'Admin',
            'is_admin': True
        })

    # Check users
    for dirname in os.listdir(USERS_DIR):
        profile_path = os.path.join(USERS_DIR, dirname, 'profile.json')
        profile = read_json(profile_path)
        if profile.get('email', '').lower() == email:
            if hash_password(password) != profile.get('password_hash'):
                return jsonify({'error': 'Invalid password'}), 401
            if profile.get('status') != 'active':
                return jsonify({'error': 'Account not active. Contact your administrator.'}), 403
            allowed, current, cap = check_usage(email)
            return jsonify({
                'token': profile['token'],
                'email': email,
                'name': profile.get('name', ''),
                'is_admin': False,
                'usage': {'current': current, 'cap': cap, 'allowed': allowed}
            })

    return jsonify({'error': 'User not found'}), 404

@app.route('/api/me', methods=['GET'])
@require_token
def get_me():
    u = request.current_user
    if u.get('is_admin'):
        return jsonify({'email': u['email'], 'name': 'Admin', 'is_admin': True})
    email = u['email']
    allowed, current, cap = check_usage(email)
    return jsonify({
        'email': email,
        'name': u.get('name', ''),
        'is_admin': False,
        'usage': {'current': current, 'cap': cap, 'allowed': allowed}
    })

@app.route('/api/change-password', methods=['POST'])
@require_token
def change_password():
    u = request.current_user
    data = request.get_json()
    new_pw = data.get('password', '')
    if len(new_pw) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    if u.get('is_admin'):
        admin = get_admin()
        admin['password_hash'] = hash_password(new_pw)
        write_json(ADMIN_FILE, admin)
        return jsonify({'ok': True})

    email = u['email']
    path = user_file(email, 'profile.json')
    profile = read_json(path)
    profile['password_hash'] = hash_password(new_pw)
    write_json(path, profile)
    return jsonify({'ok': True})

# ══════════════════════════════════════
# PLAYBOOK ROUTES
# ══════════════════════════════════════

@app.route('/api/playbook', methods=['GET'])
@require_token
def get_playbook():
    u = request.current_user
    if u.get('is_admin'):
        # Admin gets company param
        company = request.args.get('company', '__admin__')
        path = os.path.join(COMP_DIR, _safe(company), 'playbook.json')
    else:
        path = user_file(u['email'], 'playbook.json')
    return jsonify(read_json(path, {}))

@app.route('/api/playbook', methods=['POST'])
@require_token
def save_playbook():
    u = request.current_user
    data = request.get_json()
    if u.get('is_admin'):
        company = request.args.get('company', '__admin__')
        path = os.path.join(COMP_DIR, _safe(company), 'playbook.json')
    else:
        path = user_file(u['email'], 'playbook.json')
    write_json(path, data)
    return jsonify({'ok': True})

@app.route('/api/keys', methods=['GET'])
@require_token
def get_keys():
    u = request.current_user
    if u.get('is_admin'):
        # Admin keys stored in admin.json
        admin = get_admin()
        return jsonify(admin.get('keys', {}))
    path = user_file(u['email'], 'keys.json')
    return jsonify(read_json(path, {}))

@app.route('/api/keys', methods=['POST'])
@require_token
def save_keys():
    u = request.current_user
    data = request.get_json()
    if u.get('is_admin'):
        admin = get_admin()
        admin['keys'] = data
        write_json(ADMIN_FILE, admin)
        return jsonify({'ok': True})
    path = user_file(u['email'], 'keys.json')
    write_json(path, data)
    return jsonify({'ok': True})

# ══════════════════════════════════════
# USAGE TRACKING ROUTE
# ══════════════════════════════════════

@app.route('/api/usage/increment', methods=['POST'])
@require_token
def track_usage():
    u = request.current_user
    if u.get('is_admin'):
        return jsonify({'ok': True, 'is_admin': True})  # Admin unlimited
    email = u['email']
    allowed, current, cap = check_usage(email)
    if not allowed:
        return jsonify({'error': 'Usage cap reached', 'current': current, 'cap': cap}), 429
    count, cap = increment_usage(email)
    return jsonify({'ok': True, 'current': count, 'cap': cap, 'remaining': cap - count})

# ══════════════════════════════════════
# ADMIN ROUTES
# ══════════════════════════════════════

@app.route('/api/admin/users', methods=['GET'])
@require_admin
def list_users():
    users = []
    for dirname in os.listdir(USERS_DIR):
        profile_path = os.path.join(USERS_DIR, dirname, 'profile.json')
        profile = read_json(profile_path)
        if not profile:
            continue
        usage = read_json(os.path.join(USERS_DIR, dirname, 'usage.json'), {'count': 0, 'cap': 100})
        has_playbook = os.path.exists(os.path.join(USERS_DIR, dirname, 'playbook.json'))
        users.append({
            'email': profile.get('email'),
            'name': profile.get('name'),
            'status': profile.get('status', 'pending'),
            'created_at': profile.get('created_at'),
            'last_login': profile.get('last_login'),
            'usage_count': usage.get('count', 0),
            'usage_cap': usage.get('cap', 100),
            'has_playbook': has_playbook
        })
    users.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return jsonify(users)

@app.route('/api/admin/users', methods=['POST'])
@require_admin
def create_user():
    data = request.get_json()
    email = (data.get('email') or '').strip().lower()
    name = data.get('name', '')
    password = data.get('password', secrets.token_urlsafe(8))
    cap = int(data.get('cap', 100))
    status = data.get('status', 'active')

    if not email:
        return jsonify({'error': 'Email required'}), 400

    # Check duplicate
    for dirname in os.listdir(USERS_DIR):
        profile_path = os.path.join(USERS_DIR, dirname, 'profile.json')
        profile = read_json(profile_path)
        if profile.get('email', '').lower() == email:
            return jsonify({'error': 'User already exists'}), 409

    token = make_token(email + str(time.time()))
    profile = {
        'email': email,
        'name': name,
        'password_hash': hash_password(password),
        'token': token,
        'status': status,
        'created_at': datetime.utcnow().isoformat(),
        'created_by': 'admin'
    }
    usage = {'count': 0, 'cap': cap, 'history': []}

    write_json(user_file(email, 'profile.json'), profile)
    write_json(user_file(email, 'usage.json'), usage)

    return jsonify({'ok': True, 'email': email, 'password': password, 'token': token})

@app.route('/api/admin/users/<path:email>', methods=['PATCH'])
@require_admin
def update_user(email):
    data = request.get_json()
    email = email.lower()
    path = user_file(email, 'profile.json')
    profile = read_json(path)
    if not profile:
        return jsonify({'error': 'User not found'}), 404

    if 'status' in data:
        profile['status'] = data['status']
    if 'name' in data:
        profile['name'] = data['name']
    if 'password' in data and data['password']:
        profile['password_hash'] = hash_password(data['password'])
    write_json(path, profile)

    if 'cap' in data:
        usage_path = user_file(email, 'usage.json')
        usage = read_json(usage_path, {'count': 0, 'cap': 100})
        usage['cap'] = int(data['cap'])
        write_json(usage_path, usage)

    return jsonify({'ok': True})

@app.route('/api/admin/users/<path:email>', methods=['DELETE'])
@require_admin
def delete_user(email):
    import shutil
    email = email.lower()
    d = user_dir(email)
    if os.path.exists(d):
        shutil.rmtree(d)
    return jsonify({'ok': True})

@app.route('/api/admin/users/<path:email>/playbook', methods=['GET'])
@require_admin
def get_user_playbook(email):
    path = user_file(email.lower(), 'playbook.json')
    return jsonify(read_json(path, {}))

@app.route('/api/admin/users/<path:email>/playbook', methods=['POST'])
@require_admin
def set_user_playbook(email):
    """Admin pre-loads a playbook template for a user"""
    data = request.get_json()
    path = user_file(email.lower(), 'playbook.json')
    write_json(path, data)
    return jsonify({'ok': True})

@app.route('/api/admin/companies', methods=['GET'])
@require_admin
def list_companies():
    companies = []
    if os.path.exists(COMP_DIR):
        for name in os.listdir(COMP_DIR):
            pb_path = os.path.join(COMP_DIR, name, 'playbook.json')
            pb = read_json(pb_path, {})
            companies.append({
                'id': name,
                'name': pb.get('rep', {}).get('company', name),
                'products': len(pb.get('products', [])),
                'created': os.path.getctime(pb_path) if os.path.exists(pb_path) else 0
            })
    return jsonify(companies)

@app.route('/api/admin/companies', methods=['POST'])
@require_admin
def create_company():
    data = request.get_json()
    name = _safe(data.get('name', ''))
    if not name:
        return jsonify({'error': 'Name required'}), 400
    path = os.path.join(COMP_DIR, name, 'playbook.json')
    if not os.path.exists(path):
        write_json(path, {'rep': {'company': data.get('name', name)}, 'products': []})
    return jsonify({'ok': True, 'id': name})

@app.route('/api/admin/companies/<name>', methods=['DELETE'])
@require_admin
def delete_company(name):
    import shutil
    d = os.path.join(COMP_DIR, _safe(name))
    if os.path.exists(d):
        shutil.rmtree(d)
    return jsonify({'ok': True})

# Copy company playbook to user
@app.route('/api/admin/copy-to-user', methods=['POST'])
@require_admin
def copy_to_user():
    data = request.get_json()
    company = _safe(data.get('company', ''))
    email = data.get('email', '').lower()
    src = os.path.join(COMP_DIR, company, 'playbook.json')
    if not os.path.exists(src):
        return jsonify({'error': 'Company playbook not found'}), 404
    pb = read_json(src)
    write_json(user_file(email, 'playbook.json'), pb)
    return jsonify({'ok': True})

# ══════════════════════════════════════
# STATIC FILES
# ══════════════════════════════════════

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    email = (data.get('email') or '').strip().lower()
    name = data.get('name', '')
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    # Check duplicate
    for dirname in os.listdir(USERS_DIR):
        profile_path = os.path.join(USERS_DIR, dirname, 'profile.json')
        profile = read_json(profile_path)
        if profile.get('email', '').lower() == email:
            return jsonify({'error': 'An account with this email already exists'}), 409

    token = make_token(email + str(time.time()))
    profile = {
        'email': email,
        'name': name,
        'password_hash': hash_password(password),
        'token': token,
        'status': 'pending',  # Requires admin activation
        'created_at': datetime.utcnow().isoformat()
    }
    usage = {'count': 0, 'cap': 50, 'history': []}  # Default 50 cap for self-registered
    write_json(user_file(email, 'profile.json'), profile)
    write_json(user_file(email, 'usage.json'), usage)
    return jsonify({'ok': True, 'message': 'Account created — awaiting admin activation'})

@app.route('/admin')
def admin_page():
    return send_from_directory('static', 'admin.html')

@app.route('/auth.js')
def auth_js():
    return send_from_directory('static', 'auth.js')

@app.route('/app')
def app_page():
    return send_from_directory('static', 'app.html')

@app.route('/')
def index():
    return send_from_directory('static', 'login.html')



# ── helpers ──
def _safe(s):
    import re
    return re.sub(r'[^a-zA-Z0-9_-]', '_', s).lower()[:50]

if __name__ == '__main__':
    get_admin()  # Bootstrap admin on first run
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
