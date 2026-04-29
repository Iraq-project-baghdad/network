import base64
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / 'public'
DATA_DIR = BASE_DIR / 'data'
DB_PATH = DATA_DIR / 'app.db'
SECRET_PATH = DATA_DIR / 'server_secret.key'
HOST = '0.0.0.0'
PORT = int(os.environ.get('PORT', '3000'))
TEMP_GROUP_SECONDS = 24 * 60 * 60
SECURE_ROOM_IDLE_SECONDS = 12 * 60 * 60

DATA_DIR.mkdir(exist_ok=True)
if not SECRET_PATH.exists():
    SECRET_PATH.write_bytes(secrets.token_bytes(32))
SERVER_SECRET = SECRET_PATH.read_bytes()


def now() -> int:
    return int(time.time())


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def add_column_if_missing(conn, table: str, col: str, sql: str):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {sql}")


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                username_lc TEXT NOT NULL UNIQUE,
                pass_salt TEXT NOT NULL,
                pass_hash TEXT NOT NULL,
                device_id TEXT NOT NULL UNIQUE,
                avatar_data TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                bio TEXT NOT NULL DEFAULT '',
                lat REAL,
                lng REAL,
                location_updated_at INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS groups_tbl (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                privacy TEXT NOT NULL CHECK(privacy IN ('public','private')),
                lifetime TEXT NOT NULL DEFAULT 'permanent' CHECK(lifetime IN ('permanent','temp24')),
                expires_at INTEGER,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                district TEXT NOT NULL,
                cover_data TEXT DEFAULT '',
                owner_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                last_activity INTEGER NOT NULL,
                deleted_at INTEGER,
                FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS memberships (
                group_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                status TEXT NOT NULL CHECK(status IN ('accepted','pending','rejected')),
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(group_id, user_id),
                FOREIGN KEY(group_id) REFERENCES groups_tbl(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                body_enc TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(group_id) REFERENCES groups_tbl(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS captions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body_enc TEXT NOT NULL,
                body_preview TEXT NOT NULL,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                district TEXT NOT NULL,
                owner_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                last_activity INTEGER NOT NULL,
                FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS caption_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                caption_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                body_enc TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(caption_id) REFERENCES captions(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS secure_rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                share_token TEXT NOT NULL UNIQUE,
                owner_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                last_activity INTEGER NOT NULL,
                deleted_at INTEGER,
                FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS secure_members (
                room_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at INTEGER NOT NULL,
                last_seen INTEGER NOT NULL,
                PRIMARY KEY(room_id, user_id),
                FOREIGN KEY(room_id) REFERENCES secure_rooms(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS secure_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                body_enc TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(room_id) REFERENCES secure_rooms(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                ref_type TEXT NOT NULL DEFAULT '',
                ref_id INTEGER,
                created_at INTEGER NOT NULL,
                read_at INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS direct_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                body_enc TEXT NOT NULL,
                group_id INTEGER,
                created_at INTEGER NOT NULL,
                read_at INTEGER,
                FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(receiver_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(group_id) REFERENCES groups_tbl(id) ON DELETE SET NULL
            );
            """
        )
        # Migrations for older clean-neon builds.
        add_column_if_missing(conn, 'users', 'avatar_data', "avatar_data TEXT NOT NULL DEFAULT ''")
        add_column_if_missing(conn, 'users', 'phone', "phone TEXT NOT NULL DEFAULT ''")
        add_column_if_missing(conn, 'users', 'address', "address TEXT NOT NULL DEFAULT ''")
        add_column_if_missing(conn, 'users', 'bio', "bio TEXT NOT NULL DEFAULT ''")
        add_column_if_missing(conn, 'users', 'lat', "lat REAL")
        add_column_if_missing(conn, 'users', 'lng', "lng REAL")
        add_column_if_missing(conn, 'users', 'location_updated_at', "location_updated_at INTEGER")
        add_column_if_missing(conn, 'groups_tbl', 'lifetime', "lifetime TEXT NOT NULL DEFAULT 'permanent'")
        add_column_if_missing(conn, 'groups_tbl', 'expires_at', "expires_at INTEGER")
        add_column_if_missing(conn, 'groups_tbl', 'district', "district TEXT NOT NULL DEFAULT 'بغداد'")
        add_column_if_missing(conn, 'groups_tbl', 'cover_data', "cover_data TEXT DEFAULT ''")


def cleanup():
    t = now()
    with db() as conn:
        conn.execute("UPDATE groups_tbl SET deleted_at=? WHERE deleted_at IS NULL AND lifetime='temp24' AND expires_at IS NOT NULL AND expires_at<=?", (t, t))
        conn.execute("UPDATE secure_rooms SET deleted_at=? WHERE deleted_at IS NULL AND last_activity<?", (t, t - SECURE_ROOM_IDLE_SECONDS))


def hash_password(password: str, salt_b64: str | None = None):
    salt = base64.b64decode(salt_b64) if salt_b64 else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 180000)
    return base64.b64encode(salt).decode(), base64.b64encode(digest).decode()


def verify_password(password: str, salt_b64: str, expected_b64: str) -> bool:
    _, got = hash_password(password, salt_b64)
    return hmac.compare_digest(got, expected_b64)


def text_ok(text: str, max_len=1000):
    return isinstance(text, str) and 0 < len(text.strip()) <= max_len


def username_ok(name: str) -> bool:
    return bool(re.fullmatch(r"[\w\u0600-\u06FF ._-]{2,28}", name.strip(), re.UNICODE))


def safe_info(text: str, max_len: int) -> str:
    text = str(text or '').strip()
    return text[:max_len]


def image_ok(data: str) -> bool:
    return isinstance(data, str) and data.startswith('data:image/') and len(data) <= 1_600_000


def stream_cipher(data: bytes, nonce: bytes) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < len(data):
        block = hashlib.sha256(SERVER_SECRET + nonce + counter.to_bytes(4, 'big')).digest()
        out.extend(block)
        counter += 1
    return bytes(a ^ b for a, b in zip(data, out[:len(data)]))


def encrypt_text(text: str) -> str:
    nonce = secrets.token_bytes(12)
    raw = text.encode('utf-8')
    enc = stream_cipher(raw, nonce)
    tag = hmac.new(SERVER_SECRET, nonce + enc, hashlib.sha256).digest()[:12]
    return base64.b64encode(nonce + tag + enc).decode()


def decrypt_text(payload: str) -> str:
    try:
        raw = base64.b64decode(payload)
        nonce, tag, enc = raw[:12], raw[12:24], raw[24:]
        good = hmac.new(SERVER_SECRET, nonce + enc, hashlib.sha256).digest()[:12]
        if not hmac.compare_digest(tag, good):
            return '[رسالة تالفة]'
        return stream_cipher(enc, nonce).decode('utf-8', 'replace')
    except Exception:
        return '[رسالة غير مقروءة]'


def json_response(handler, payload, status=200):
    raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.send_header('Content-Length', str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def read_json(handler):
    size = int(handler.headers.get('Content-Length', '0') or 0)
    if size > 2_500_000:
        raise ValueError('payload too large')
    raw = handler.rfile.read(size) if size else b'{}'
    return json.loads(raw.decode('utf-8')) if raw else {}


def bearer_token(handler):
    auth = handler.headers.get('Authorization', '')
    return auth.split(' ', 1)[1].strip() if auth.lower().startswith('bearer ') else ''


def public_user(row):
    lat = row['lat'] if 'lat' in row.keys() else None
    lng = row['lng'] if 'lng' in row.keys() else None
    return {
        'id': row['id'],
        'username': row['username'],
        'avatarData': row['avatar_data'] or '',
        'phone': row['phone'] or '',
        'address': row['address'] or '',
        'bio': row['bio'] or '',
        'lat': lat,
        'lng': lng,
        'hasLocation': lat is not None and lng is not None,
        'locationUpdatedAt': row['location_updated_at'] if 'location_updated_at' in row.keys() else None,
        'createdAt': row['created_at']
    }


def current_user(handler):
    token = bearer_token(handler)
    if not token:
        return None
    with db() as conn:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
            (token,)
        ).fetchone()
        return public_user(row) | {'deviceId': row['device_id']} if row else None


def require_user(handler):
    user = current_user(handler)
    if not user:
        json_response(handler, {'ok': False, 'error': 'تحتاج تسجيل دخول.'}, 401)
        return None
    return user


def detect_district(lat, lng):
    places = [
        ('الكرادة', 33.309, 44.437), ('الزعفرانية', 33.228, 44.482), ('المنصور', 33.306, 44.352),
        ('الأعظمية', 33.378, 44.375), ('الكرخ', 33.311, 44.345), ('الرصافة', 33.340, 44.440),
        ('مدينة الصدر', 33.381, 44.479), ('اليرموك', 33.290, 44.314), ('العدل', 33.346, 44.295),
        ('الدورة', 33.229, 44.357), ('العامرية', 33.290, 44.280), ('الجادرية', 33.278, 44.385),
        ('الغزالية', 33.333, 44.258), ('الجامعة', 33.300, 44.306), ('الشعب', 33.407, 44.469),
        ('بغداد الجديدة', 33.310, 44.489), ('الغدير', 33.313, 44.474), ('البلديات', 33.365, 44.497),
        ('الرحمانية', 33.360, 44.335), ('الوشاش', 33.309, 44.331), ('حي الجامعة', 33.293, 44.291),
        ('الكاظمية', 33.381, 44.337), ('البياع', 33.251, 44.330), ('البتاوين', 33.331, 44.418),
        ('الحارثية', 33.312, 44.330), ('النهضة', 33.347, 44.430), ('الشيخ عمر', 33.338, 44.426)
    ]
    best = min(places, key=lambda p: (lat - p[1]) ** 2 + (lng - p[2]) ** 2)
    return best[0]


def haversine_m(lat1, lng1, lat2, lng2):
    R = 6371000
    p1 = math.radians(float(lat1)); p2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lng2) - float(lng1))
    a = math.sin(dphi/2)**2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))


def add_notification(conn, user_id, kind, title, body, ref_type='', ref_id=None):
    conn.execute(
        "INSERT INTO notifications(user_id,kind,title,body,ref_type,ref_id,created_at) VALUES(?,?,?,?,?,?,?)",
        (user_id, kind, title, body[:280], ref_type, ref_id, now())
    )


def notify_nearby_users(actor_id, lat, lng, kind, title, body, ref_type, ref_id, radius_m=120):
    with db() as conn:
        rows = conn.execute("SELECT id,lat,lng FROM users WHERE id<>? AND lat IS NOT NULL AND lng IS NOT NULL", (actor_id,)).fetchall()
        for r in rows:
            try:
                if haversine_m(lat, lng, r['lat'], r['lng']) <= radius_m:
                    add_notification(conn, r['id'], kind, title, body, ref_type, ref_id)
            except Exception:
                pass


def group_dict(row, user_id=None):
    with db() as conn:
        owner = conn.execute("SELECT * FROM users WHERE id=?", (row['owner_id'],)).fetchone()
        mem = conn.execute("SELECT COUNT(*) c FROM memberships WHERE group_id=? AND status='accepted'", (row['id'],)).fetchone()['c']
        my_status = None
        my_role = None
        if user_id:
            m = conn.execute("SELECT status, role FROM memberships WHERE group_id=? AND user_id=?", (row['id'], user_id)).fetchone()
            if m:
                my_status = m['status']
                my_role = m['role']
    expires_in = None
    if row['lifetime'] == 'temp24' and row['expires_at']:
        expires_in = max(0, int(row['expires_at']) - now())
    return {
        'id': row['id'], 'name': row['name'], 'privacy': row['privacy'], 'lifetime': row['lifetime'],
        'expiresAt': row['expires_at'], 'expiresIn': expires_in,
        'lat': row['lat'], 'lng': row['lng'], 'district': row['district'],
        'coverData': row['cover_data'] or '', 'ownerId': row['owner_id'],
        'owner': owner['username'] if owner else 'غير معروف',
        'ownerAvatar': owner['avatar_data'] if owner else '',
        'createdAt': row['created_at'], 'lastActivity': row['last_activity'],
        'members': mem, 'myStatus': my_status, 'myRole': my_role
    }


def caption_dict(row):
    with db() as conn:
        owner = conn.execute("SELECT * FROM users WHERE id=?", (row['owner_id'],)).fetchone()
        count = conn.execute("SELECT COUNT(*) c FROM caption_comments WHERE caption_id=?", (row['id'],)).fetchone()['c']
    body = decrypt_text(row['body_enc'])
    return {
        'id': row['id'], 'title': row['title'], 'body': body, 'bodyPreview': row['body_preview'],
        'lat': row['lat'], 'lng': row['lng'], 'district': row['district'],
        'ownerId': row['owner_id'], 'owner': owner['username'] if owner else 'غير معروف',
        'ownerAvatar': owner['avatar_data'] if owner else '',
        'createdAt': row['created_at'], 'lastActivity': row['last_activity'], 'commentsCount': count
    }


def secure_room_dict(row, user_id):
    with db() as conn:
        members = conn.execute(
            "SELECT u.id,u.username,u.avatar_data,m.joined_at,m.last_seen FROM secure_members m JOIN users u ON u.id=m.user_id WHERE m.room_id=? ORDER BY m.joined_at ASC",
            (row['id'],)
        ).fetchall()
    return {
        'id': row['id'], 'title': row['title'], 'shareToken': row['share_token'],
        'ownerId': row['owner_id'], 'createdAt': row['created_at'], 'lastActivity': row['last_activity'],
        'isOwner': row['owner_id'] == user_id,
        'members': [{'id': r['id'], 'username': r['username'], 'avatarData': r['avatar_data'] or '', 'joinedAt': r['joined_at'], 'lastSeen': r['last_seen']} for r in members]
    }


class Handler(SimpleHTTPRequestHandler):
    server_version = 'BaghdadChatLiveNeon/3.0'

    def translate_path(self, path):
        parsed = urllib.parse.urlparse(path)
        rel = urllib.parse.unquote(parsed.path).lstrip('/') or 'index.html'
        safe = Path(rel)
        if any(part in ('..', '') for part in safe.parts if part != '.'):
            return str(PUBLIC_DIR / 'index.html')
        return str(PUBLIC_DIR / safe)

    def end_headers(self):
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        super().end_headers()

    def do_GET(self):
        cleanup()
        path = urllib.parse.urlparse(self.path).path
        if path == '/favicon.ico':
            fav = PUBLIC_DIR / 'favicon.svg'
            if fav.exists():
                raw = fav.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'image/svg+xml')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
        if path.startswith('/api/'):
            try:
                return self.api_get(path)
            except Exception as exc:
                return json_response(self, {'ok': False, 'error': f'Server error: {exc}'}, 500)
        return super().do_GET()

    def do_POST(self):
        cleanup()
        path = urllib.parse.urlparse(self.path).path
        if not path.startswith('/api/'):
            return json_response(self, {'ok': False, 'error': 'Not found'}, 404)
        try:
            return self.api_post(path)
        except json.JSONDecodeError:
            return json_response(self, {'ok': False, 'error': 'JSON غير صحيح.'}, 400)
        except Exception as exc:
            return json_response(self, {'ok': False, 'error': f'Server error: {exc}'}, 500)

    def do_PUT(self):
        cleanup()
        path = urllib.parse.urlparse(self.path).path
        if not path.startswith('/api/'):
            return json_response(self, {'ok': False, 'error': 'Not found'}, 404)
        try:
            return self.api_put(path)
        except Exception as exc:
            return json_response(self, {'ok': False, 'error': f'Server error: {exc}'}, 500)

    def api_get(self, path):
        if path == '/api/me':
            return json_response(self, {'ok': True, 'user': current_user(self)})

        if path == '/api/snapshot':
            user = current_user(self)
            user_id = user['id'] if user else None
            with db() as conn:
                rows = conn.execute("SELECT * FROM groups_tbl WHERE deleted_at IS NULL ORDER BY last_activity DESC").fetchall()
                caps = conn.execute("SELECT * FROM captions ORDER BY last_activity DESC").fetchall()
            return json_response(self, {'ok': True, 'groups': [group_dict(r, user_id) for r in rows], 'captions': [caption_dict(r) for r in caps], 'serverTime': now()})

        if path == '/api/people':
            user = require_user(self)
            if not user: return
            with db() as conn:
                rows = conn.execute("SELECT * FROM users ORDER BY username_lc ASC").fetchall()
            return json_response(self, {'ok': True, 'people': [public_user(r) for r in rows]})

        if path == '/api/notifications':
            user = require_user(self)
            if not user: return
            with db() as conn:
                rows = conn.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 80", (user['id'],)).fetchall()
                unread = conn.execute("SELECT COUNT(*) c FROM notifications WHERE user_id=? AND read_at IS NULL", (user['id'],)).fetchone()['c']
            return json_response(self, {'ok': True, 'unread': unread, 'notifications': [dict(r) for r in rows]})

        if path == '/api/direct_messages':
            user = require_user(self)
            if not user: return
            with db() as conn:
                rows = conn.execute(
                    """SELECT dm.*, su.username sender_name, su.avatar_data sender_avatar, ru.username receiver_name, ru.avatar_data receiver_avatar, g.name group_name
                    FROM direct_messages dm
                    JOIN users su ON su.id=dm.sender_id
                    JOIN users ru ON ru.id=dm.receiver_id
                    LEFT JOIN groups_tbl g ON g.id=dm.group_id
                    WHERE dm.sender_id=? OR dm.receiver_id=? ORDER BY dm.id DESC LIMIT 120""",
                    (user['id'], user['id'])
                ).fetchall()
                conn.execute("UPDATE direct_messages SET read_at=? WHERE receiver_id=? AND read_at IS NULL", (now(), user['id']))
            msgs=[]
            for r in rows:
                d=dict(r)
                d['text']=decrypt_text(d.pop('body_enc'))
                d['mine']=d['sender_id']==user['id']
                msgs.append(d)
            return json_response(self, {'ok': True, 'messages': msgs})

        m = re.fullmatch(r'/api/users/(\d+)', path)
        if m:
            user = require_user(self)
            if not user: return
            uid = int(m.group(1))
            with db() as conn:
                row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not row:
                return json_response(self, {'ok': False, 'error': 'المستخدم غير موجود.'}, 404)
            return json_response(self, {'ok': True, 'user': public_user(row)})

        m = re.fullmatch(r'/api/groups/(\d+)/messages', path)
        if m:
            user = require_user(self)
            if not user: return
            gid = int(m.group(1))
            if not self.can_read_group(gid, user['id']):
                return json_response(self, {'ok': False, 'error': 'ليست لديك صلاحية القراءة.'}, 403)
            with db() as conn:
                rows = conn.execute(
                    "SELECT m.id,m.body_enc,m.created_at,u.username,u.avatar_data,u.id user_id FROM messages m JOIN users u ON u.id=m.user_id WHERE m.group_id=? ORDER BY m.id ASC LIMIT 500",
                    (gid,)
                ).fetchall()
            return json_response(self, {'ok': True, 'messages': [{
                'id': r['id'], 'text': decrypt_text(r['body_enc']), 'createdAt': r['created_at'],
                'username': r['username'], 'avatarData': r['avatar_data'] or '', 'userId': r['user_id'], 'mine': r['user_id'] == user['id']
            } for r in rows]})

        m = re.fullmatch(r'/api/groups/(\d+)/requests', path)
        if m:
            user = require_user(self)
            if not user: return
            gid = int(m.group(1))
            if not self.is_owner(gid, user['id']):
                return json_response(self, {'ok': False, 'error': 'هذا الخيار للمالك فقط.'}, 403)
            with db() as conn:
                rows = conn.execute("SELECT u.id,u.username,u.avatar_data,ms.created_at FROM memberships ms JOIN users u ON u.id=ms.user_id WHERE ms.group_id=? AND ms.status='pending' ORDER BY ms.created_at ASC", (gid,)).fetchall()
            return json_response(self, {'ok': True, 'requests': [{'id': r['id'], 'username': r['username'], 'avatarData': r['avatar_data'] or '', 'createdAt': r['created_at']} for r in rows]})

        m = re.fullmatch(r'/api/captions/(\d+)/comments', path)
        if m:
            require = require_user(self)
            if not require: return
            cid = int(m.group(1))
            with db() as conn:
                rows = conn.execute("SELECT c.id,c.body_enc,c.created_at,u.username,u.avatar_data,u.id user_id FROM caption_comments c JOIN users u ON u.id=c.user_id WHERE c.caption_id=? ORDER BY c.id ASC", (cid,)).fetchall()
            return json_response(self, {'ok': True, 'comments': [{
                'id': r['id'], 'text': decrypt_text(r['body_enc']), 'createdAt': r['created_at'], 'username': r['username'], 'avatarData': r['avatar_data'] or '', 'userId': r['user_id']
            } for r in rows]})

        m = re.fullmatch(r'/api/secure_rooms/by_token/([A-Za-z0-9_-]{16,120})', path)
        if m:
            user = require_user(self)
            if not user: return
            token = m.group(1)
            with db() as conn:
                row = conn.execute("SELECT * FROM secure_rooms WHERE share_token=? AND deleted_at IS NULL", (token,)).fetchone()
                if not row:
                    return json_response(self, {'ok': False, 'error': 'رابط الدردشة المشفرة منتهي أو محذوف.'}, 404)
                conn.execute("INSERT OR IGNORE INTO secure_members(room_id,user_id,joined_at,last_seen) VALUES(?,?,?,?)", (row['id'], user['id'], now(), now()))
                conn.execute("UPDATE secure_members SET last_seen=? WHERE room_id=? AND user_id=?", (now(), row['id'], user['id']))
                conn.execute("UPDATE secure_rooms SET last_activity=? WHERE id=?", (now(), row['id']))
                row = conn.execute("SELECT * FROM secure_rooms WHERE id=?", (row['id'],)).fetchone()
            return json_response(self, {'ok': True, 'room': secure_room_dict(row, user['id'])})

        m = re.fullmatch(r'/api/secure_rooms/(\d+)/messages', path)
        if m:
            user = require_user(self)
            if not user: return
            rid = int(m.group(1))
            if not self.is_secure_member(rid, user['id']):
                return json_response(self, {'ok': False, 'error': 'هذه الدردشة فائقة التشفير تحتاج رابط دخول.'}, 403)
            with db() as conn:
                rows = conn.execute("SELECT sm.id,sm.body_enc,sm.created_at,u.username,u.avatar_data,u.id user_id FROM secure_messages sm JOIN users u ON u.id=sm.user_id WHERE sm.room_id=? ORDER BY sm.id ASC LIMIT 500", (rid,)).fetchall()
                room = conn.execute("SELECT * FROM secure_rooms WHERE id=? AND deleted_at IS NULL", (rid,)).fetchone()
                conn.execute("UPDATE secure_members SET last_seen=? WHERE room_id=? AND user_id=?", (now(), rid, user['id']))
            if not room:
                return json_response(self, {'ok': False, 'error': 'انتهت الدردشة.'}, 404)
            return json_response(self, {'ok': True, 'room': secure_room_dict(room, user['id']), 'messages': [{
                'id': r['id'], 'text': decrypt_text(r['body_enc']), 'createdAt': r['created_at'], 'username': r['username'], 'avatarData': r['avatar_data'] or '', 'userId': r['user_id'], 'mine': r['user_id'] == user['id']
            } for r in rows]})

        return json_response(self, {'ok': False, 'error': 'Not found'}, 404)

    def api_post(self, path):
        payload = read_json(self)

        if path == '/api/location':
            user = require_user(self)
            if not user: return
            try:
                lat = float(payload.get('lat'))
                lng = float(payload.get('lng'))
            except Exception:
                return json_response(self, {'ok': False, 'error': 'الموقع غير صالح.'}, 400)
            with db() as conn:
                conn.execute("UPDATE users SET lat=?, lng=?, location_updated_at=?, updated_at=? WHERE id=?", (lat, lng, now(), now(), user['id']))
            return json_response(self, {'ok': True})

        if path == '/api/direct_messages':
            user = require_user(self)
            if not user: return
            try:
                receiver_id = int(payload.get('receiverId'))
            except Exception:
                return json_response(self, {'ok': False, 'error': 'اختر الشخص المستلم.'}, 400)
            text = str(payload.get('text', '')).strip()
            if not text_ok(text, 1000):
                return json_response(self, {'ok': False, 'error': 'الرسالة فارغة أو طويلة.'}, 400)
            group_id = payload.get('groupId')
            try:
                group_id = int(group_id) if group_id else None
            except Exception:
                group_id = None
            with db() as conn:
                if not conn.execute("SELECT id FROM users WHERE id=?", (receiver_id,)).fetchone():
                    return json_response(self, {'ok': False, 'error': 'المستخدم غير موجود.'}, 404)
                cur = conn.execute("INSERT INTO direct_messages(sender_id,receiver_id,body_enc,group_id,created_at) VALUES(?,?,?,?,?)", (user['id'], receiver_id, encrypt_text(text), group_id, now()))
                dm_id = cur.lastrowid
                add_notification(conn, receiver_id, 'dm', 'رسالة خاصة جديدة', f"{user['username']}: {text[:120]}", 'dm', dm_id)
            return json_response(self, {'ok': True, 'messageId': dm_id})

        m = re.fullmatch(r'/api/notifications/(\d+)/read', path)
        if m:
            user = require_user(self)
            if not user: return
            nid = int(m.group(1))
            with db() as conn:
                conn.execute("UPDATE notifications SET read_at=? WHERE id=? AND user_id=?", (now(), nid, user['id']))
            return json_response(self, {'ok': True})

        if path == '/api/account/register':
            device_id = str(payload.get('deviceId', '')).strip()
            username = str(payload.get('username', '')).strip()
            password = str(payload.get('password', ''))
            avatar_data = str(payload.get('avatarData', '')).strip()
            phone = safe_info(payload.get('phone', ''), 40)
            address = safe_info(payload.get('address', ''), 120)
            bio = safe_info(payload.get('bio', ''), 240)
            if len(device_id) < 20:
                return json_response(self, {'ok': False, 'error': 'معرف الجهاز غير صالح.'}, 400)
            if not username_ok(username):
                return json_response(self, {'ok': False, 'error': 'اسم المستخدم يجب أن يكون من 2 إلى 28 حرف.'}, 400)
            if len(password) < 6:
                return json_response(self, {'ok': False, 'error': 'كلمة المرور قصيرة.'}, 400)
            if not image_ok(avatar_data):
                return json_response(self, {'ok': False, 'error': 'يجب رفع صورة شخصية للحساب.'}, 400)
            with db() as conn:
                if conn.execute("SELECT id FROM users WHERE device_id=?", (device_id,)).fetchone():
                    return json_response(self, {'ok': False, 'error': 'هذا الجهاز لديه حساب مسبقاً ولا يمكن إنشاء حساب ثاني.'}, 409)
                if conn.execute("SELECT id FROM users WHERE username_lc=?", (username.lower(),)).fetchone():
                    return json_response(self, {'ok': False, 'error': 'اسم المستخدم مستخدم، اختر غيره.'}, 409)
                salt, digest = hash_password(password)
                cur = conn.execute("INSERT INTO users(username,username_lc,pass_salt,pass_hash,device_id,avatar_data,phone,address,bio,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (username, username.lower(), salt, digest, device_id, avatar_data, phone, address, bio, now(), now()))
                uid = cur.lastrowid
                token = secrets.token_urlsafe(32)
                conn.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)", (token, uid, now()))
                row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            return json_response(self, {'ok': True, 'token': token, 'user': public_user(row) | {'deviceId': device_id}})

        if path == '/api/account/login':
            device_id = str(payload.get('deviceId', '')).strip()
            username = str(payload.get('username', '')).strip()
            password = str(payload.get('password', ''))
            with db() as conn:
                row = conn.execute("SELECT * FROM users WHERE username_lc=?", (username.lower(),)).fetchone()
                if not row or not verify_password(password, row['pass_salt'], row['pass_hash']):
                    return json_response(self, {'ok': False, 'error': 'الاسم أو كلمة المرور خطأ.'}, 401)
                if row['device_id'] != device_id:
                    return json_response(self, {'ok': False, 'error': 'هذا الحساب مربوط بجهاز آخر.'}, 403)
                token = secrets.token_urlsafe(32)
                conn.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)", (token, row['id'], now()))
            return json_response(self, {'ok': True, 'token': token, 'user': public_user(row) | {'deviceId': row['device_id']}})

        if path == '/api/account/logout':
            token = bearer_token(self)
            if token:
                with db() as conn:
                    conn.execute("DELETE FROM sessions WHERE token=?", (token,))
            return json_response(self, {'ok': True})

        if path == '/api/account/device_reset':
            device_id = str(payload.get('deviceId', '')).strip()
            if len(device_id) < 20:
                return json_response(self, {'ok': False, 'error': 'معرف الجهاز غير صالح.'}, 400)
            with db() as conn:
                row = conn.execute("SELECT id FROM users WHERE device_id=?", (device_id,)).fetchone()
                if row:
                    conn.execute("DELETE FROM sessions WHERE user_id=?", (row['id'],))
                    conn.execute("DELETE FROM users WHERE id=?", (row['id'],))
                    return json_response(self, {'ok': True, 'deleted': True, 'message': 'تم حذف الحساب المرتبط بهذا الجهاز.'})
            return json_response(self, {'ok': True, 'deleted': False, 'message': 'لا يوجد حساب محفوظ لهذا الجهاز.'})

        if path == '/api/groups':
            user = require_user(self)
            if not user: return
            name = str(payload.get('name', '')).strip()
            privacy = str(payload.get('privacy', 'public')).strip()
            lifetime = str(payload.get('lifetime', 'permanent')).strip()
            try:
                lat = float(payload.get('lat'))
                lng = float(payload.get('lng'))
            except Exception:
                return json_response(self, {'ok': False, 'error': 'الموقع غير صالح.'}, 400)
            if not text_ok(name, 50):
                return json_response(self, {'ok': False, 'error': 'اسم الدردشة مطلوب.'}, 400)
            if privacy not in ('public', 'private'):
                return json_response(self, {'ok': False, 'error': 'نوع الدردشة غير صالح.'}, 400)
            if lifetime not in ('permanent', 'temp24'):
                return json_response(self, {'ok': False, 'error': 'مدة الدردشة غير صحيحة.'}, 400)
            if not (32.8 <= lat <= 34.2 and 43.6 <= lng <= 45.2):
                return json_response(self, {'ok': False, 'error': 'الموقع خارج نطاق بغداد تقريباً.'}, 400)
            district = detect_district(lat, lng)
            clean_name = name if district in name else f"{name} - {district}"
            expires_at = now() + TEMP_GROUP_SECONDS if lifetime == 'temp24' else None
            with db() as conn:
                cur = conn.execute("INSERT INTO groups_tbl(name,privacy,lifetime,expires_at,lat,lng,district,owner_id,created_at,last_activity) VALUES(?,?,?,?,?,?,?,?,?,?)", (clean_name, privacy, lifetime, expires_at, lat, lng, district, user['id'], now(), now()))
                gid = cur.lastrowid
                conn.execute("INSERT INTO memberships(group_id,user_id,role,status,created_at,updated_at) VALUES(?,?,?,?,?,?)", (gid, user['id'], 'owner', 'accepted', now(), now()))
                row = conn.execute("SELECT * FROM groups_tbl WHERE id=?", (gid,)).fetchone()
            notify_nearby_users(user['id'], lat, lng, 'near_group', 'دردشة قريبة من موقعك', f'صارت دردشة قريبة من موقعك: {clean_name}', 'group', gid)
            return json_response(self, {'ok': True, 'group': group_dict(row, user['id'])})

        m = re.fullmatch(r'/api/groups/(\d+)/join', path)
        if m:
            user = require_user(self)
            if not user: return
            gid = int(m.group(1))
            with db() as conn:
                group = conn.execute("SELECT * FROM groups_tbl WHERE id=? AND deleted_at IS NULL", (gid,)).fetchone()
                if not group:
                    return json_response(self, {'ok': False, 'error': 'الدردشة غير موجودة.'}, 404)
                existing = conn.execute("SELECT * FROM memberships WHERE group_id=? AND user_id=?", (gid, user['id'])).fetchone()
                if existing:
                    return json_response(self, {'ok': True, 'status': existing['status'], 'message': 'الطلب موجود مسبقاً.'})
                status = 'accepted' if group['privacy'] == 'public' else 'pending'
                conn.execute("INSERT INTO memberships(group_id,user_id,role,status,created_at,updated_at) VALUES(?,?,?,?,?,?)", (gid, user['id'], 'member', status, now(), now()))
            return json_response(self, {'ok': True, 'status': status, 'message': 'تم الدخول للدردشة.' if status == 'accepted' else 'تم إرسال طلب الدخول.'})

        m = re.fullmatch(r'/api/groups/(\d+)/messages', path)
        if m:
            user = require_user(self)
            if not user: return
            gid = int(m.group(1))
            text = str(payload.get('text', '')).strip()
            if not text_ok(text, 1000):
                return json_response(self, {'ok': False, 'error': 'الرسالة فارغة أو طويلة.'}, 400)
            if not self.can_write_group(gid, user['id']):
                return json_response(self, {'ok': False, 'error': 'لا يمكنك الكتابة داخل هذه الدردشة.'}, 403)
            with db() as conn:
                conn.execute("INSERT INTO messages(group_id,user_id,body_enc,created_at) VALUES(?,?,?,?)", (gid, user['id'], encrypt_text(text), now()))
                conn.execute("UPDATE groups_tbl SET last_activity=? WHERE id=?", (now(), gid))
            return json_response(self, {'ok': True})

        m = re.fullmatch(r'/api/groups/(\d+)/requests/(\d+)/(accept|reject)', path)
        if m:
            user = require_user(self)
            if not user: return
            gid = int(m.group(1)); uid = int(m.group(2)); action = m.group(3)
            if not self.is_owner(gid, user['id']):
                return json_response(self, {'ok': False, 'error': 'هذا الخيار للمالك فقط.'}, 403)
            new_status = 'accepted' if action == 'accept' else 'rejected'
            with db() as conn:
                conn.execute("UPDATE memberships SET status=?, updated_at=? WHERE group_id=? AND user_id=? AND status='pending'", (new_status, now(), gid, uid))
            return json_response(self, {'ok': True, 'status': new_status})

        m = re.fullmatch(r'/api/groups/(\d+)/cover', path)
        if m:
            user = require_user(self)
            if not user: return
            gid = int(m.group(1))
            image_data = str(payload.get('imageData', '')).strip()
            if not image_ok(image_data):
                return json_response(self, {'ok': False, 'error': 'الملف ليس صورة أو كبير جداً.'}, 400)
            if not self.can_write_group(gid, user['id']):
                return json_response(self, {'ok': False, 'error': 'لا تملك صلاحية تعديل الغلاف.'}, 403)
            with db() as conn:
                conn.execute("UPDATE groups_tbl SET cover_data=?, last_activity=? WHERE id=? AND deleted_at IS NULL", (image_data, now(), gid))
            return json_response(self, {'ok': True})

        if path == '/api/captions':
            user = require_user(self)
            if not user: return
            title = str(payload.get('title', '')).strip()
            text = str(payload.get('text', '')).strip()
            try:
                lat = float(payload.get('lat'))
                lng = float(payload.get('lng'))
            except Exception:
                return json_response(self, {'ok': False, 'error': 'الموقع غير صالح.'}, 400)
            if not text_ok(title, 70):
                return json_response(self, {'ok': False, 'error': 'عنوان الكتابة مطلوب.'}, 400)
            if not text_ok(text, 1200):
                return json_response(self, {'ok': False, 'error': 'تفاصيل الكتابة مطلوبة.'}, 400)
            district = detect_district(lat, lng)
            preview = text[:90] + ('...' if len(text) > 90 else '')
            with db() as conn:
                cur = conn.execute("INSERT INTO captions(title,body_enc,body_preview,lat,lng,district,owner_id,created_at,last_activity) VALUES(?,?,?,?,?,?,?,?,?)", (title, encrypt_text(text), preview, lat, lng, district, user['id'], now(), now()))
                cid = cur.lastrowid
                row = conn.execute("SELECT * FROM captions WHERE id=?", (cid,)).fetchone()
            notify_nearby_users(user['id'], lat, lng, 'near_caption', 'كتابة قريبة من موقعك', f'أحد كتب فوق موقع قريب منك: {title}', 'caption', cid)
            return json_response(self, {'ok': True, 'caption': caption_dict(row)})

        m = re.fullmatch(r'/api/captions/(\d+)/comments', path)
        if m:
            user = require_user(self)
            if not user: return
            cid = int(m.group(1))
            text = str(payload.get('text', '')).strip()
            if not text_ok(text, 700):
                return json_response(self, {'ok': False, 'error': 'التعليق فارغ أو طويل.'}, 400)
            with db() as conn:
                exists = conn.execute("SELECT id FROM captions WHERE id=?", (cid,)).fetchone()
                if not exists:
                    return json_response(self, {'ok': False, 'error': 'الكتابة غير موجودة.'}, 404)
                conn.execute("INSERT INTO caption_comments(caption_id,user_id,body_enc,created_at) VALUES(?,?,?,?)", (cid, user['id'], encrypt_text(text), now()))
                conn.execute("UPDATE captions SET last_activity=? WHERE id=?", (now(), cid))
            return json_response(self, {'ok': True})

        if path == '/api/secure_rooms':
            user = require_user(self)
            if not user: return
            title = str(payload.get('title', '')).strip() or 'دردشة فائقة التشفير'
            if not text_ok(title, 70):
                return json_response(self, {'ok': False, 'error': 'اسم الدردشة المشفرة غير صالح.'}, 400)
            share_token = secrets.token_urlsafe(32)
            with db() as conn:
                cur = conn.execute("INSERT INTO secure_rooms(title,share_token,owner_id,created_at,last_activity) VALUES(?,?,?,?,?)", (title, share_token, user['id'], now(), now()))
                rid = cur.lastrowid
                conn.execute("INSERT INTO secure_members(room_id,user_id,joined_at,last_seen) VALUES(?,?,?,?)", (rid, user['id'], now(), now()))
                row = conn.execute("SELECT * FROM secure_rooms WHERE id=?", (rid,)).fetchone()
            return json_response(self, {'ok': True, 'room': secure_room_dict(row, user['id'])})

        m = re.fullmatch(r'/api/secure_rooms/(\d+)/messages', path)
        if m:
            user = require_user(self)
            if not user: return
            rid = int(m.group(1))
            text = str(payload.get('text', '')).strip()
            if not text_ok(text, 1000):
                return json_response(self, {'ok': False, 'error': 'الرسالة فارغة أو طويلة.'}, 400)
            if not self.is_secure_member(rid, user['id']):
                return json_response(self, {'ok': False, 'error': 'لا يمكنك الكتابة داخل هذه الدردشة.'}, 403)
            with db() as conn:
                room = conn.execute("SELECT id FROM secure_rooms WHERE id=? AND deleted_at IS NULL", (rid,)).fetchone()
                if not room:
                    return json_response(self, {'ok': False, 'error': 'انتهت الدردشة.'}, 404)
                conn.execute("INSERT INTO secure_messages(room_id,user_id,body_enc,created_at) VALUES(?,?,?,?)", (rid, user['id'], encrypt_text(text), now()))
                conn.execute("UPDATE secure_rooms SET last_activity=? WHERE id=?", (now(), rid))
                conn.execute("UPDATE secure_members SET last_seen=? WHERE room_id=? AND user_id=?", (now(), rid, user['id']))
            return json_response(self, {'ok': True})

        m = re.fullmatch(r'/api/secure_rooms/(\d+)/(leave|delete)', path)
        if m:
            user = require_user(self)
            if not user: return
            rid = int(m.group(1)); action = m.group(2)
            with db() as conn:
                room = conn.execute("SELECT * FROM secure_rooms WHERE id=? AND deleted_at IS NULL", (rid,)).fetchone()
                if not room:
                    return json_response(self, {'ok': True, 'deleted': True})
                if action == 'delete' or room['owner_id'] == user['id']:
                    conn.execute("UPDATE secure_rooms SET deleted_at=?, last_activity=? WHERE id=?", (now(), now(), rid))
                    return json_response(self, {'ok': True, 'deleted': True})
                conn.execute("DELETE FROM secure_members WHERE room_id=? AND user_id=?", (rid, user['id']))
            return json_response(self, {'ok': True, 'deleted': False})

        return json_response(self, {'ok': False, 'error': 'Not found'}, 404)

    def api_put(self, path):
        payload = read_json(self)
        if path != '/api/account':
            return json_response(self, {'ok': False, 'error': 'Not found'}, 404)
        user = require_user(self)
        if not user: return
        current_password = str(payload.get('currentPassword', ''))
        new_username = str(payload.get('username', '')).strip()
        new_password = str(payload.get('password', ''))
        avatar_data = str(payload.get('avatarData', '')).strip()
        phone = safe_info(payload.get('phone', ''), 40)
        address = safe_info(payload.get('address', ''), 120)
        bio = safe_info(payload.get('bio', ''), 240)
        if not current_password:
            return json_response(self, {'ok': False, 'error': 'اكتب كلمة المرور الحالية.'}, 400)
        with db() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (user['id'],)).fetchone()
            if not row or not verify_password(current_password, row['pass_salt'], row['pass_hash']):
                return json_response(self, {'ok': False, 'error': 'كلمة المرور الحالية غير صحيحة.'}, 401)
            updates, params = [], []
            if new_username and new_username != row['username']:
                if not username_ok(new_username):
                    return json_response(self, {'ok': False, 'error': 'اسم المستخدم غير صالح.'}, 400)
                if conn.execute("SELECT id FROM users WHERE username_lc=? AND id<>?", (new_username.lower(), user['id'])).fetchone():
                    return json_response(self, {'ok': False, 'error': 'اسم المستخدم مستخدم، اختر غيره.'}, 409)
                updates += ['username=?', 'username_lc=?']
                params += [new_username, new_username.lower()]
            if new_password:
                if len(new_password) < 6:
                    return json_response(self, {'ok': False, 'error': 'كلمة المرور الجديدة قصيرة.'}, 400)
                salt, digest = hash_password(new_password)
                updates += ['pass_salt=?', 'pass_hash=?']
                params += [salt, digest]
            updates += ['phone=?', 'address=?', 'bio=?']
            params += [phone, address, bio]
            if avatar_data:
                if not image_ok(avatar_data):
                    return json_response(self, {'ok': False, 'error': 'الصورة غير صالحة أو كبيرة.'}, 400)
                updates.append('avatar_data=?')
                params.append(avatar_data)
            updates.append('updated_at=?')
            params.append(now())
            params.append(user['id'])
            conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id=?", params)
            fresh = conn.execute("SELECT * FROM users WHERE id=?", (user['id'],)).fetchone()
        return json_response(self, {'ok': True, 'user': public_user(fresh) | {'deviceId': fresh['device_id']}})

    def is_owner(self, gid, uid):
        with db() as conn:
            row = conn.execute("SELECT owner_id FROM groups_tbl WHERE id=? AND deleted_at IS NULL", (gid,)).fetchone()
        return bool(row and row['owner_id'] == uid)

    def can_read_group(self, gid, uid):
        with db() as conn:
            g = conn.execute("SELECT privacy FROM groups_tbl WHERE id=? AND deleted_at IS NULL", (gid,)).fetchone()
            if not g:
                return False
            if g['privacy'] == 'public':
                return True
            m = conn.execute("SELECT status FROM memberships WHERE group_id=? AND user_id=?", (gid, uid)).fetchone()
            return bool(m and m['status'] == 'accepted')

    def can_write_group(self, gid, uid):
        with db() as conn:
            m = conn.execute("SELECT ms.status FROM memberships ms JOIN groups_tbl g ON g.id=ms.group_id WHERE ms.group_id=? AND ms.user_id=? AND g.deleted_at IS NULL", (gid, uid)).fetchone()
            return bool(m and m['status'] == 'accepted')

    def is_secure_member(self, rid, uid):
        with db() as conn:
            r = conn.execute("SELECT id FROM secure_rooms WHERE id=? AND deleted_at IS NULL", (rid,)).fetchone()
            if not r:
                return False
            m = conn.execute("SELECT 1 FROM secure_members WHERE room_id=? AND user_id=?", (rid, uid)).fetchone()
            return bool(m)


def main():
    init_db()
    print('=====================================================')
    print(' Baghdad Chat Live Neon - Python Server')
    print(f' Open: http://localhost:{PORT}')
    print(' One-account-per-device + live map + secure rooms')
    print('=====================================================')
    os.chdir(PUBLIC_DIR)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.serve_forever()


if __name__ == '__main__':
    main()
