from datetime import datetime
from pathlib import Path
import csv
import hashlib
import hmac
import io
import json
import os
import sqlite3
import uuid

from flask import Flask, render_template, request, make_response, Response, redirect, url_for

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("QUICK_CAPTURE_DB", str(BASE_DIR / "quick_capture.db")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
ADMIN_PASSWORD = os.environ.get("QUICK_CAPTURE_ADMIN_PASSWORD", "")
ADMIN_COOKIE = "qc_admin"

app = Flask(__name__, template_folder=str(BASE_DIR / "app" / "templates"), static_folder=str(BASE_DIR / "app" / "static"))


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn, table_name, column_name, alter_sql):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(alter_sql)


def init_db():
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inbox_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'inbox',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL DEFAULT 'default',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            device_id TEXT NOT NULL,
            device_name TEXT,
            token_hash TEXT,
            trusted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_seen_at TEXT
        )
        """
    )
    ensure_column(conn, "inbox_items", "user_id", "ALTER TABLE inbox_items ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "inbox_items", "source_device_id", "ALTER TABLE inbox_items ADD COLUMN source_device_id TEXT")
    ensure_column(conn, "users", "approval_status", "ALTER TABLE users ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'approved'")
    ensure_column(conn, "users", "join_code", "ALTER TABLE users ADD COLUMN join_code TEXT")
    ensure_column(conn, "users", "approved_at", "ALTER TABLE users ADD COLUMN approved_at TEXT")
    ensure_column(conn, "devices", "provision_source", "ALTER TABLE devices ADD COLUMN provision_source TEXT NOT NULL DEFAULT 'direct'")
    ensure_column(conn, "devices", "pending_approval", "ALTER TABLE devices ADD COLUMN pending_approval INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "users", "api_token", "ALTER TABLE users ADD COLUMN api_token TEXT")
    conn.execute("UPDATE inbox_items SET user_id = 1 WHERE user_id IS NULL")
    conn.execute("UPDATE users SET approved_at = COALESCE(approved_at, created_at) WHERE approval_status = 'approved'")
    conn.commit()
    conn.close()


def admin_cookie_value():
    if not ADMIN_PASSWORD:
        return None
    return hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()


def is_admin_authenticated():
    expected = admin_cookie_value()
    if not expected:
        return True
    actual = request.cookies.get(ADMIN_COOKIE, "")
    return hmac.compare_digest(actual, expected)


def admin_guard():
    if is_admin_authenticated():
        return None
    next_path = request.path
    if request.query_string:
        next_path += "?" + request.query_string.decode()
    return redirect(url_for("admin_login_page", next=next_path))


def generate_join_code():
    return uuid.uuid4().hex[:12]


def create_pending_user(conn):
    name = f"user-{uuid.uuid4().hex[:6]}"
    join_code = generate_join_code()
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO users (name, approval_status, join_code, created_at) VALUES (?, 'pending', ?, ?)",
        (name, join_code, now),
    )
    user_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return user_id


def ensure_user_join_code(conn, user_id):
    row = conn.execute("SELECT join_code FROM users WHERE id = ?", (user_id,)).fetchone()
    if row and not row["join_code"]:
        conn.execute("UPDATE users SET join_code = ? WHERE id = ?", (generate_join_code(), user_id))


def get_or_create_device(device_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT d.id, d.user_id, d.device_id, d.device_name, d.trusted, d.provision_source, d.pending_approval, u.approval_status, u.join_code, u.name AS user_name FROM devices d JOIN users u ON u.id = d.user_id WHERE d.device_id = ?",
        (device_id,)
    ).fetchone()
    if not row:
        user_id = create_pending_user(conn)
        provision_source = "first-visit"
        trusted = 0
        conn.execute(
            "INSERT INTO devices (user_id, device_id, device_name, trusted, provision_source) VALUES (?, ?, 'Unknown', ?, ?)",
            (user_id, device_id, trusted, provision_source)
        )
        conn.commit()
        row = conn.execute(
            "SELECT d.id, d.user_id, d.device_id, d.device_name, d.trusted, d.provision_source, d.pending_approval, u.approval_status, u.join_code, u.name AS user_name FROM devices d JOIN users u ON u.id = d.user_id WHERE d.device_id = ?",
            (device_id,)
        ).fetchone()
    conn.execute(
        "UPDATE devices SET last_seen_at = ? WHERE device_id = ?",
        (datetime.now().isoformat(timespec="seconds"), device_id),
    )
    conn.commit()
    conn.close()
    return dict(row)


def get_items(user_id=None, q=None):
    conn = get_conn()
    if user_id:
        if q:
            rows = conn.execute(
                "SELECT id, user_id, source_device_id, content, status, created_at, updated_at FROM inbox_items WHERE user_id = ? AND content LIKE ? ORDER BY created_at DESC, id DESC",
                (user_id, f"%{q}%")
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, user_id, source_device_id, content, status, created_at, updated_at FROM inbox_items WHERE user_id = ? ORDER BY created_at DESC, id DESC",
                (user_id,)
            ).fetchall()
    else:
        if q:
            rows = conn.execute(
                "SELECT id, user_id, source_device_id, content, status, created_at, updated_at FROM inbox_items WHERE content LIKE ? ORDER BY created_at DESC, id DESC",
                (f"%{q}%",)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, user_id, source_device_id, content, status, created_at, updated_at FROM inbox_items ORDER BY created_at DESC, id DESC"
            ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_account_items(user_id, q=None):
    conn = get_conn()
    user = conn.execute('SELECT id, name, created_at, approval_status, join_code, approved_at FROM users WHERE id = ?', (user_id,)).fetchone()
    if q:
        rows = conn.execute(
            """
            SELECT i.id, i.user_id, i.source_device_id, i.content, i.status, i.created_at, i.updated_at,
                   COALESCE(d.device_name, 'Unknown') AS source_device_name
            FROM inbox_items i
            LEFT JOIN devices d ON d.device_id = i.source_device_id
            WHERE i.user_id = ? AND i.content LIKE ?
            ORDER BY i.created_at DESC, i.id DESC
            """,
            (user_id, f"%{q}%")
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT i.id, i.user_id, i.source_device_id, i.content, i.status, i.created_at, i.updated_at,
                   COALESCE(d.device_name, 'Unknown') AS source_device_name
            FROM inbox_items i
            LEFT JOIN devices d ON d.device_id = i.source_device_id
            WHERE i.user_id = ?
            ORDER BY i.created_at DESC, i.id DESC
            """,
            (user_id,)
        ).fetchall()
    conn.close()
    return (dict(user) if user else {"id": user_id, "name": f"user-{user_id}", "created_at": None}, [dict(r) for r in rows])


def get_device_items(device_id):
    conn = get_conn()
    device = conn.execute(
        "SELECT d.id, d.user_id, d.device_id, d.device_name, d.trusted, d.provision_source, d.created_at, d.last_seen_at, u.approval_status FROM devices d JOIN users u ON u.id = d.user_id WHERE d.device_id = ?",
        (device_id,)
    ).fetchone()
    rows = conn.execute(
        "SELECT id, user_id, source_device_id, content, status, created_at, updated_at FROM inbox_items WHERE source_device_id = ? ORDER BY created_at DESC, id DESC",
        (device_id,)
    ).fetchall()
    conn.close()
    return (dict(device) if device else None, [dict(r) for r in rows])


def get_devices(user_id=None, pending_approval=None):
    conn = get_conn()
    query = """
        SELECT
            d.id,
            d.user_id,
            d.device_id,
            d.device_name,
            d.trusted,
            d.provision_source,
            d.pending_approval,
            d.created_at,
            d.last_seen_at,
            u.approval_status,
            COUNT(i.id) AS item_count
        FROM devices d
        JOIN users u ON u.id = d.user_id
        LEFT JOIN inbox_items i ON i.source_device_id = d.device_id
        WHERE 1 = 1
    """
    params = []
    if user_id is not None:
        query += " AND d.user_id = ?"
        params.append(user_id)
    if pending_approval is not None:
        query += " AND d.pending_approval = ?"
        params.append(1 if pending_approval else 0)
    query += " GROUP BY d.id, d.user_id, d.device_id, d.device_name, d.trusted, d.provision_source, d.pending_approval, d.created_at, d.last_seen_at, u.approval_status ORDER BY COALESCE(d.last_seen_at, d.created_at) DESC, d.id DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_users(approval_status=None):
    conn = get_conn()
    query = """
        SELECT u.id, u.name, u.approval_status, u.join_code, u.created_at, u.approved_at,
               COUNT(DISTINCT d.id) AS device_count,
               COUNT(i.id) AS item_count
        FROM users u
        LEFT JOIN devices d ON d.user_id = u.id
        LEFT JOIN inbox_items i ON i.user_id = u.id
        WHERE 1 = 1
    """
    params = []
    if approval_status is not None:
        query += " AND u.approval_status = ?"
        params.append(approval_status)
    query += " GROUP BY u.id, u.name, u.approval_status, u.join_code, u.created_at, u.approved_at ORDER BY u.created_at DESC, u.id DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def approve_user(user_id):
    conn = get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    token = uuid.uuid4().hex[:16]
    conn.execute(
        "UPDATE users SET approval_status = 'approved', approved_at = COALESCE(approved_at, ?), join_code = COALESCE(join_code, ?), api_token = COALESCE(api_token, ?) WHERE id = ?",
        (now, generate_join_code(), token, user_id),
    )
    conn.commit()
    conn.close()


def join_account_by_code(device_id, join_code):
    clean_code = (join_code or "").strip()
    if not clean_code:
        return False, "请输入加入码。"
    conn = get_conn()
    user = conn.execute(
        "SELECT id, approval_status FROM users WHERE join_code = ?",
        (clean_code,),
    ).fetchone()
    if not user:
        conn.close()
        return False, "加入码无效。"
    if user["approval_status"] != "approved":
        conn.close()
        return False, "这个账号还没开通。"
    # 先检查设备是否已存在
    existing = conn.execute("SELECT user_id FROM devices WHERE device_id = ?", (device_id,)).fetchone()
    if existing:
        # 设备已存在，改 user_id 但设为 pending
        conn.execute(
            "UPDATE devices SET user_id = ?, provision_source = 'join-code', pending_approval = 1, last_seen_at = ? WHERE device_id = ?",
            (user["id"], datetime.now().isoformat(timespec="seconds"), device_id),
        )
    else:
        # 新设备，创建并设为 pending
        conn.execute(
            "INSERT INTO devices (user_id, device_id, device_name, trusted, provision_source, pending_approval) VALUES (?, ?, 'Unknown', 0, 'join-code', 1)",
            (user["id"], device_id),
        )
    conn.execute(
        "UPDATE inbox_items SET user_id = ? WHERE source_device_id = ?",
        (user["id"], device_id),
    )
    conn.commit()
    conn.close()
    return True, None


def get_account_summary(user_id):
    conn = get_conn()
    user = conn.execute('SELECT id, name, created_at, approval_status, join_code, approved_at, api_token FROM users WHERE id = ?', (user_id,)).fetchone()
    device_count = conn.execute('SELECT COUNT(*) AS c FROM devices WHERE user_id = ?', (user_id,)).fetchone()["c"]
    item_count = conn.execute('SELECT COUNT(*) AS c FROM inbox_items WHERE user_id = ?', (user_id,)).fetchone()["c"]
    trusted_device_count = conn.execute('SELECT COUNT(*) AS c FROM devices WHERE user_id = ? AND trusted = 1', (user_id,)).fetchone()["c"]
    conn.close()
    return {
        "user": dict(user) if user else {"id": user_id, "name": f"user-{user_id}", "created_at": None},
        "device_count": device_count,
        "item_count": item_count,
        "trusted_device_count": trusted_device_count,
    }


def update_device_name(device_id, device_name):
    clean_name = (device_name or "").strip()[:80]
    if not clean_name:
        clean_name = "Unknown"
    conn = get_conn()
    conn.execute(
        "UPDATE devices SET device_name = ?, last_seen_at = ? WHERE device_id = ?",
        (clean_name, datetime.now().isoformat(timespec="seconds"), device_id),
    )
    conn.commit()
    conn.close()


def update_user_name(user_id, user_name):
    clean_name = (user_name or "").strip()[:80]
    if not clean_name:
        clean_name = f"user-{user_id}"
    conn = get_conn()
    conn.execute("UPDATE users SET name = ? WHERE id = ?", (clean_name, user_id))
    conn.commit()
    conn.close()


def ensure_user_api_token(user_id):
    conn = get_conn()
    row = conn.execute("SELECT api_token FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or not row["api_token"]:
        prefix = uuid.uuid4().hex[:8]
        token = prefix
        conn.execute("UPDATE users SET api_token = ? WHERE id = ?", (token, user_id))
        conn.commit()
        conn.close()
        return prefix
    conn.close()
    return row["api_token"]


def update_user_api_token(user_id, user_suffix, keep_prefix=True):
    clean_suffix = (user_suffix or "").strip()
    conn = get_conn()
    row = conn.execute("SELECT api_token FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        conn.close()
        return False, "用户不存在"
    if not clean_suffix:
        if keep_prefix and row["api_token"]:
            prefix = row["api_token"][:8]
            conn.execute("UPDATE users SET api_token = ? WHERE id = ?", (prefix, user_id))
        else:
            conn.execute("UPDATE users SET api_token = NULL WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
        return True, None
    if not clean_suffix.isalnum():
        conn.close()
        return False, "后缀只能包含数字和英文"
    if len(clean_suffix) > 20:
        conn.close()
        return False, "后缀不能超过 20 个字符"
    prefix = row["api_token"][:8] if row["api_token"] else uuid.uuid4().hex[:8]
    new_token = prefix + clean_suffix
    existing = conn.execute("SELECT id FROM users WHERE api_token = ? AND id != ?", (new_token, user_id)).fetchone()
    if existing:
        conn.close()
        return False, "该 token 已被其他用户使用，请换一个后缀"
    conn.execute("UPDATE users SET api_token = ? WHERE id = ?", (new_token, user_id))
    conn.commit()
    conn.close()
    return True, None


def get_user_by_token(token):
    conn = get_conn()
    user = conn.execute("SELECT id, name FROM users WHERE api_token = ?", (token,)).fetchone()
    conn.close()
    return dict(user) if user else None


def get_records_by_time(user_id, since=None):
    conn = get_conn()
    if since:
        if since.endswith("h"):
            hours = int(since[:-1])
            time_filter = f"datetime('now', '-{hours} hours')"
        elif since.endswith("d"):
            days = int(since[:-1])
            time_filter = f"datetime('now', '-{days} days')"
        elif since.endswith("m"):
            minutes = int(since[:-1])
            time_filter = f"datetime('now', '-{minutes} minutes')"
        else:
            time_filter = "datetime('now', '-1 hours')"
        rows = conn.execute(
            f"SELECT id, content, status, created_at FROM inbox_items WHERE user_id = ? AND created_at >= {time_filter} ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, content, status, created_at FROM inbox_items WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def approve_device_from_group(current_device_id, target_device_id):
    """组内任意设备都可以批准其他设备"""
    conn = get_conn()
    current = conn.execute("SELECT user_id, pending_approval FROM devices WHERE device_id = ?", (current_device_id,)).fetchone()
    if not current or current["pending_approval"]:
        conn.close()
        return False, "当前设备还未被批准，无权审批"
    target = conn.execute("SELECT user_id, pending_approval FROM devices WHERE device_id = ?", (target_device_id,)).fetchone()
    if not target or not target["pending_approval"]:
        conn.close()
        return False, "该设备不需要批准"
    if current["user_id"] != target["user_id"]:
        conn.close()
        return False, "只能批准同组设备"
    conn.execute("UPDATE devices SET pending_approval = 0 WHERE device_id = ?", (target_device_id,))
    conn.commit()
    conn.close()
    return True, None


def toggle_device_trusted(device_id):
    conn = get_conn()
    row = conn.execute("SELECT trusted FROM devices WHERE device_id = ?", (device_id,)).fetchone()
    if row:
        next_trusted = 0 if row["trusted"] else 1
        conn.execute(
            "UPDATE devices SET trusted = ?, last_seen_at = ? WHERE device_id = ?",
            (next_trusted, datetime.now().isoformat(timespec="seconds"), device_id),
        )
        conn.commit()
    conn.close()


def remove_device_from_account(current_device_id, target_device_id):
    if not current_device_id or current_device_id == target_device_id:
        return False
    conn = get_conn()
    current = conn.execute("SELECT user_id FROM devices WHERE device_id = ?", (current_device_id,)).fetchone()
    target = conn.execute("SELECT user_id FROM devices WHERE device_id = ?", (target_device_id,)).fetchone()
    if not current or not target or current["user_id"] != target["user_id"]:
        conn.close()
        return False
    conn.execute("DELETE FROM devices WHERE device_id = ?", (target_device_id,))
    conn.commit()
    conn.close()
    return True


def build_export_filename(ext):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"quick-capture-export-{timestamp}.{ext}"


init_db()


@app.route("/")
def index():
    device_id = request.cookies.get("qc_device_id")
    if not device_id:
        device_id = str(uuid.uuid4())
    device = get_or_create_device(device_id)
    items = []
    if device.get("approval_status") == "approved" and not device.get("pending_approval"):
        items = get_items(device["user_id"])
    resp = make_response(render_template("index.html", device=device, items=items))
    resp.set_cookie("qc_device_id", device_id, max_age=31536000, httponly=True)
    return resp


@app.route("/admin/login", methods=["GET"])
def admin_login_page():
    return render_template("admin_login.html", error=None)


@app.route("/admin/login", methods=["POST"])
def admin_login_submit():
    next_url = request.args.get("next") or request.form.get("next") or "/admin/accounts"
    password = request.form.get("password", "")
    if ADMIN_PASSWORD and password == ADMIN_PASSWORD:
        resp = make_response(redirect(next_url))
        resp.set_cookie(ADMIN_COOKIE, admin_cookie_value(), max_age=604800, httponly=True)
        return resp
    return render_template("admin_login.html", error="密码不对，请再试一次。")


@app.route("/admin/logout", methods=["GET", "POST"])
def admin_logout():
    resp = make_response(redirect("/"))
    resp.set_cookie(ADMIN_COOKIE, "", expires=0)
    return resp


@app.route("/join", methods=["GET"])
def join_page():
    device_id = request.cookies.get("qc_device_id")
    if not device_id:
        device_id = str(uuid.uuid4())
    device = get_or_create_device(device_id)
    resp = make_response(render_template("join.html", device=device, error=None, success=None))
    resp.set_cookie("qc_device_id", device_id, max_age=31536000, httponly=True)
    return resp


@app.route("/join", methods=["POST"])
def join_submit():
    device_id = request.cookies.get("qc_device_id")
    if not device_id:
        device_id = str(uuid.uuid4())
    device = get_or_create_device(device_id)
    ok, error = join_account_by_code(device_id, request.form.get("join_code", ""))
    joined_device = get_or_create_device(device_id)
    if ok:
        success_msg = "已提交加入申请，等待组内设备批准后即可查看记录。"
    else:
        success_msg = None
    resp = make_response(render_template("join.html", device=joined_device, error=error, success=success_msg))
    resp.set_cookie("qc_device_id", device_id, max_age=31536000, httponly=True)
    return resp


@app.route("/admin/accounts")
def admin_accounts_page():
    guard = admin_guard()
    if guard:
        return guard
    pending_users = get_users("pending")
    approved_users = get_users("approved")
    return render_template("admin_accounts.html", pending_users=pending_users, approved_users=approved_users)


@app.route("/admin/accounts/approve/<int:user_id>", methods=["POST"])
def approve_user_route(user_id):
    guard = admin_guard()
    if guard:
        return guard
    approve_user(user_id)
    return redirect(url_for("admin_accounts_page"))


@app.route("/me")
def me_page():
    device_id = request.cookies.get("qc_device_id")
    if not device_id:
        return redirect(url_for("index"))
    device = get_or_create_device(device_id)
    if device.get("pending_approval"):
        return redirect(url_for("index"))
    summary = get_account_summary(device["user_id"])
    devices = get_devices(user_id=device["user_id"], pending_approval=False)
    pending_devices = get_devices(user_id=device["user_id"], pending_approval=True)
    return render_template("me.html", summary=summary, devices=devices, pending_devices=pending_devices, current_device_id=device_id, is_admin=is_admin_authenticated())


@app.route("/me/rename-account", methods=["POST"])
def rename_account():
    device_id = request.cookies.get("qc_device_id")
    if not device_id:
        return redirect(url_for("index"))
    device = get_or_create_device(device_id)
    update_user_name(device["user_id"], request.form.get("user_name", ""))
    return redirect(url_for("me_page"))


@app.route("/me/update-token", methods=["POST"])
def update_token():
    device_id = request.cookies.get("qc_device_id")
    if not device_id:
        return redirect(url_for("index"))
    device = get_or_create_device(device_id)
    user_suffix = request.form.get("token_suffix", "")
    ok, error = update_user_api_token(device["user_id"], user_suffix)
    summary = get_account_summary(device["user_id"])
    devices = get_devices(user_id=device["user_id"])
    return render_template("me.html", summary=summary, devices=devices, current_device_id=device_id, is_admin=is_admin_authenticated(), token_error=error if not ok else None, token_success="API Token 已更新" if ok else None)


@app.route("/account")
def account_page():
    return redirect(url_for("me_page"))


@app.route("/devices")
def devices_page():
    return redirect(url_for("me_page"))


@app.route("/account/items")
def account_items_page():
    guard = admin_guard()
    if guard:
        return guard
    raw_user_id = request.args.get("user_id")
    if raw_user_id:
        user_id = int(raw_user_id)
    else:
        approved_users = get_users("approved")
        if not approved_users:
            return redirect(url_for("admin_accounts_page"))
        user_id = approved_users[0]["id"]
    q = request.args.get("q", "").strip()
    user, items = get_account_items(user_id, q if q else None)
    return render_template("account_items.html", user=user, items=items, q=q)


@app.route("/devices/<device_id>/items")
def device_items_page(device_id):
    guard = admin_guard()
    if guard:
        return guard
    device, items = get_device_items(device_id)
    return render_template("device_items.html", device=device, items=items)


@app.route("/devices/rename/<device_id>", methods=["POST"])
def rename_device(device_id):
    current_device_id = request.cookies.get("qc_device_id")
    if current_device_id == device_id:
        update_device_name(device_id, request.form.get("device_name", ""))
        return redirect(url_for("index"))
    guard = admin_guard()
    if guard:
        return guard
    update_device_name(device_id, request.form.get("device_name", ""))
    return redirect(url_for("devices_page"))


@app.route("/devices/toggle-trusted/<device_id>", methods=["POST"])
def toggle_device(device_id):
    guard = admin_guard()
    if guard:
        return guard
    toggle_device_trusted(device_id)
    return redirect(url_for("devices_page"))


@app.route("/me/remove-device/<device_id>", methods=["POST"])
def remove_device(device_id):
    current_device_id = request.cookies.get("qc_device_id")
    remove_device_from_account(current_device_id, device_id)
    return redirect(url_for("me_page"))


@app.route("/me/approve-device/<device_id>", methods=["POST"])
def approve_device(device_id):
    current_device_id = request.cookies.get("qc_device_id")
    ok, error = approve_device_from_group(current_device_id, device_id)
    if not ok:
        return redirect(url_for("me_page"))
    return redirect(url_for("me_page"))


@app.route("/add", methods=["POST"])
def add_item():
    raw = request.form.get("content", "")
    device_id = request.cookies.get("qc_device_id")
    device = get_or_create_device(device_id) if device_id else None
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    added_count = 0
    if lines:
        now = datetime.now().isoformat(timespec="seconds")
        conn = get_conn()
        for content in lines:
            conn.execute(
                "INSERT INTO inbox_items (user_id, source_device_id, content, status, created_at, updated_at) VALUES (?, ?, ?, 'inbox', ?, ?)",
                (device["user_id"] if device else 1, device_id, content, now, now),
            )
            added_count += 1
        conn.commit()
        conn.close()
    if device and device.get("approval_status") == "approved":
        items = get_items(device["user_id"])
        return render_template("_subtle_list.html", items=items[:5])
    return render_template("_capture_result.html", added_count=added_count)


@app.route("/api/records")
def api_records():
    token = request.args.get("token", "")
    since = request.args.get("since", "")
    user = get_user_by_token(token)
    if not user:
        return Response(json.dumps({"error": "无效 token"}), status=401, mimetype="application/json")
    records = get_records_by_time(user["id"], since if since else None)
    return Response(json.dumps({"user": user["name"], "count": len(records), "records": records}, ensure_ascii=False), mimetype="application/json")


@app.route("/export.csv")
def export_csv():
    guard = admin_guard()
    if guard:
        return guard
    items = get_items()
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["id", "user_id", "source_device_id", "content", "status", "created_at", "updated_at"])
    writer.writeheader()
    writer.writerows(items)
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={build_export_filename('csv')}"},
    )


@app.route("/export.json")
def export_json():
    guard = admin_guard()
    if guard:
        return guard
    payload = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "items": get_items(),
    }
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={build_export_filename('json')}"},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=18901, debug=False)
