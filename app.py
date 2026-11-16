
import os
import io
import json
import sqlite3
import secrets
import smtplib
import shutil
from datetime import datetime, timedelta
from functools import wraps
from email.message import EmailMessage

from flask import (
    Flask, request, redirect, url_for, session,
    flash, render_template_string, send_file, abort
)
from werkzeug.security import generate_password_hash, check_password_hash


# =========================================================
# YH RESTAURANT MANAGEMENT SYSTEM
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "yosha_restaurant_v2.db")

app = Flask(__name__)
app.secret_key = os.environ.get("YH_SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024


# =========================================================
# DATABASE
# =========================================================

def db():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'cashier',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT DEFAULT '',
        price REAL NOT NULL DEFAULT 0,
        cost REAL NOT NULL DEFAULT 0,
        stock REAL NOT NULL DEFAULT 0,
        low_stock REAL NOT NULL DEFAULT 5,
        image TEXT DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS stock_moves (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        quantity REAL NOT NULL,
        reason TEXT NOT NULL,
        note TEXT DEFAULT '',
        user_id INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY(product_id) REFERENCES products(id)
    );

    CREATE TABLE IF NOT EXISTS restaurant_tables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'available'
    );

    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_no TEXT NOT NULL UNIQUE,
        total REAL NOT NULL,
        discount REAL NOT NULL DEFAULT 0,
        paid REAL NOT NULL DEFAULT 0,
        payment_method TEXT DEFAULT 'cash',
        table_id INTEGER,
        status TEXT NOT NULL DEFAULT 'completed',
        user_id INTEGER,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS sale_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL,
        product_id INTEGER,
        product_name TEXT NOT NULL,
        quantity REAL NOT NULL,
        price REAL NOT NULL,
        cost REAL NOT NULL,
        subtotal REAL NOT NULL,
        FOREIGN KEY(sale_id) REFERENCES sales(id)
    );

    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        category TEXT DEFAULT '',
        amount REAL NOT NULL,
        note TEXT DEFAULT '',
        user_id INTEGER,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT NOT NULL,
        details TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS password_resets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        code TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used INTEGER NOT NULL DEFAULT 0
    );
    """)

    # Initial restaurant tables
    count = con.execute("SELECT COUNT(*) FROM restaurant_tables").fetchone()[0]
    if count == 0:
        con.executemany(
            "INSERT INTO restaurant_tables(name) VALUES (?)",
            [(f"طاولة {i}",) for i in range(1, 9)]
        )

    defaults = {
        "restaurant_name": "YH Restaurant",
        "currency": "SDG",
        "primary_color": "#c92332",
        "secondary_color": "#f4c542",
        "email_host": "",
        "email_port": "587",
        "email_user": "",
        "email_password": "",
        "email_from": "",
        "receipt_footer": "شكراً لزيارتكم",
    }

    for key, value in defaults.items():
        con.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)",
            (key, value)
        )

    con.commit()
    con.close()


def setting(key, default=""):
    con = db()
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    con.close()
    return row["value"] if row else default


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(action, details=""):
    if session.get("user_id"):
        con = db()
        con.execute(
            "INSERT INTO audit_logs(user_id,action,details,created_at) VALUES (?,?,?,?)",
            (session["user_id"], action, details, now())
        )
        con.commit()
        con.close()


def current_user():
    if not session.get("user_id"):
        return None
    con = db()
    user = con.execute(
        "SELECT * FROM users WHERE id=? AND active=1",
        (session["user_id"],)
    ).fetchone()
    con.close()
    return user


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def roles(*allowed):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            user = current_user()
            if user["role"] not in allowed:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# =========================================================
# HTML LAYOUT
# =========================================================

STYLE = """
<style>
:root {
 --red: #c92332;
 --yellow: #f4c542;
 --bg: #f5f5f7;
 --white: #fff;
 --text: #24242a;
}
* {box-sizing:border-box}
body {
 margin:0;background:var(--bg);color:var(--text);
 font-family:Arial,Tahoma,sans-serif;direction:rtl
}
header {
 background:var(--red);color:white;padding:17px 22px;
 display:flex;justify-content:space-between;align-items:center;
 flex-wrap:wrap;gap:10px
}
.logo {font-size:24px;font-weight:900;letter-spacing:2px}
nav {
 background:#292930;padding:12px;display:flex;
 gap:8px;flex-wrap:wrap
}
nav a {
 color:white;text-decoration:none;padding:10px 12px;
 border-radius:7px;font-size:14px
}
nav a:hover {background:var(--red)}
main {padding:18px;max-width:1400px;margin:auto}
.card {
 background:white;border-radius:12px;padding:17px;
 margin-bottom:15px;box-shadow:0 2px 10px #0000000a
}
.grid {
 display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
 gap:14px
}
.stat {border-right:5px solid var(--red)}
.stat h3 {margin:0 0 12px;color:#777;font-size:14px}
.stat strong {font-size:25px}
input,select,textarea {
 width:100%;padding:11px;border:1px solid #ddd;
 border-radius:7px;margin:5px 0 12px;font-size:15px;
 background:white
}
button,.btn {
 background:var(--red);color:white;border:0;border-radius:7px;
 padding:11px 16px;cursor:pointer;text-decoration:none;
 display:inline-block;font-size:14px
}
button:hover,.btn:hover {opacity:.88}
.btn-yellow {background:var(--yellow);color:#222}
.btn-dark {background:#333}
table {width:100%;border-collapse:collapse;background:white}
th,td {padding:11px;border-bottom:1px solid #eee;text-align:right}
th {background:#f4f4f4}
.table-wrap {overflow-x:auto}
.badge {padding:5px 9px;border-radius:20px;background:#eee}
.good {color:green}.bad {color:#c92332}
.alert {padding:12px;background:#fff2d0;border-radius:8px;margin:10px 0}
form.inline {display:inline}
footer{text-align:center;color:#888;padding:25px}
a {color:var(--red)}
@media(max-width:600px) {
 main{padding:10px}
 header{padding:13px}
 nav a{padding:8px;font-size:12px}
 th,td{padding:8px;font-size:13px}
}
</style>
"""

NAV = """
<nav>
<a href="/">الرئيسية</a>
<a href="/pos">نقطة البيع</a>
<a href="/products">المنتجات</a>
<a href="/stock">المخزون</a>
<a href="/tables">الطاولات</a>
<a href="/kitchen">المطبخ</a>
<a href="/orders">الطلبات</a>
<a href="/sales">المبيعات</a>
<a href="/expenses">المصروفات</a>
<a href="/reports">التقارير</a>
<a href="/users">الموظفون</a>
<a href="/logs">سجل العمليات</a>
<a href="/backup">النسخ الاحتياطي</a>
<a href="/settings">الإعدادات</a>
<a href="/logout">خروج</a>
</nav>
"""


def page(title, content, **context):
    user = current_user()
    if user:
        return render_template_string("""
        <!doctype html><html lang="ar" dir="rtl">
        <head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>{{title}}</title>
        """ + STYLE + """
        </head><body>
        <header>
          <div class="logo">YH</div>
          <div>{{restaurant}} | {{user.name}} ({{user.role}})</div>
        </header>
        """ + NAV + """
        <main>
        {% with messages=get_flashed_messages() %}
          {% for m in messages %}<div class="alert">{{m}}</div>{% endfor %}
        {% endwith %}
        <h2>{{title}}</h2>
        """ + content + """
        </main><footer>YH Restaurant Management System</footer>
        </body></html>
        """, title=title, restaurant=setting("restaurant_name"),
             user=user, **context)

    return render_template_string("""
    <!doctype html><html lang="ar" dir="rtl">
    <head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{{title}}</title>
    """ + STYLE + """
    </head><body><main>
    {% with messages=get_flashed_messages() %}
      {% for m in messages %}<div class="alert">{{m}}</div>{% endfor %}
    {% endwith %}
    """ + content + """
    </main></body></html>
    """, title=title, **context)


def money(value):
    return f"{float(value or 0):,.2f} {setting('currency','SDG')}"


# =========================================================
# FIRST INSTALL / AUTHENTICATION
# =========================================================

@app.route("/setup", methods=["GET", "POST"])
def setup():
    con = db()
    count = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    con.close()

    if count:
        return redirect(url_for("login"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or len(password) < 8:
            flash("أدخل الاسم والبريد وكلمة مرور لا تقل عن 8 أحرف")
        else:
            con = db()
            con.execute("""
                INSERT INTO users(name,email,password,role,created_at)
                VALUES(?,?,?,?,?)
            """, (name, email, generate_password_hash(password), "owner", now()))
            con.commit()
            con.close()
            flash("تم إنشاء حساب المالك. سجل الدخول الآن.")
            return redirect(url_for("login"))

    return page("إعداد حساب المالك", """
    <div class="card">
    <h3>مرحباً بك في YH Restaurant</h3>
    <form method="post">
    <label>اسم المالك</label><input name="name" required>
    <label>البريد الإلكتروني</label><input name="email" type="email" required>
    <label>كلمة المرور - 8 أحرف على الأقل</label>
    <input name="password" type="password" minlength="8" required>
    <button>إنشاء حساب المالك</button>
    </form></div>
    """)


@app.route("/login", methods=["GET", "POST"])
def login():
    con = db()
    count = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    con.close()

    if count == 0:
        return redirect(url_for("setup"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        con = db()
        user = con.execute(
            "SELECT * FROM users WHERE email=? AND active=1", (email,)
        ).fetchone()
        con.close()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            log("login", "تسجيل دخول ناجح")
            return redirect(url_for("dashboard"))

        flash("البريد الإلكتروني أو كلمة المرور غير صحيحة")

    return page("تسجيل الدخول", """
    <div class="card" style="max-width:430px;margin:40px auto">
    <h1 style="text-align:center;color:#c92332">YH</h1>
    <h3 style="text-align:center">YH Restaurant</h3>
    <form method="post">
    <label>البريد الإلكتروني</label>
    <input type="email" name="email" required>
    <label>كلمة المرور</label>
    <input type="password" name="password" required>
    <button style="width:100%">دخول</button>
    </form>
    <p><a href="/forgot">نسيت كلمة المرور؟</a></p>
    </div>
    """)


@app.route("/logout")
def logout():
    if session.get("user_id"):
        log("logout", "تسجيل خروج")
    session.clear()
    return redirect(url_for("login"))


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/")
@login_required
def dashboard():
    con = db()
    today = datetime.now().strftime("%Y-%m-%d")

    sales = con.execute("""
        SELECT COALESCE(SUM(total),0) FROM sales
        WHERE status='completed' AND substr(created_at,1,10)=?
    """, (today,)).fetchone()[0]

    expenses = con.execute("""
        SELECT COALESCE(SUM(amount),0) FROM expenses
        WHERE substr(created_at,1,10)=?
    """, (today,)).fetchone()[0]

    cost = con.execute("""
        SELECT COALESCE(SUM(si.quantity*si.cost),0)
        FROM sale_items si JOIN sales s ON s.id=si.sale_id
        WHERE s.status='completed' AND substr(s.created_at,1,10)=?
    """, (today,)).fetchone()[0]

    products = con.execute(
        "SELECT COUNT(*) FROM products WHERE active=1"
    ).fetchone()[0]

    low = con.execute(
        "SELECT COUNT(*) FROM products WHERE active=1 AND stock<=low_stock"
    ).fetchone()[0]

    recent = con.execute(
        "SELECT * FROM sales ORDER BY id DESC LIMIT 8"
    ).fetchall()

    con.close()

    net = sales - cost - expenses

    return page("لوحة التحكم", """
    <div class="grid">
      <div class="card stat"><h3>مبيعات اليوم</h3><strong>{{sales}}</strong></div>
      <div class="card stat"><h3>تكلفة البضاعة المباعة</h3><strong>{{cost}}</strong></div>
      <div class="card stat"><h3>مصروفات اليوم</h3><strong>{{expenses}}</strong></div>
      <div class="card stat"><h3>صافي الربح اليوم</h3><strong>{{net}}</strong></div>
      <div class="card stat"><h3>المنتجات</h3><strong>{{products}}</strong></div>
      <div class="card stat"><h3>أصناف منخفضة المخزون</h3><strong>{{low}}</strong></div>
    </div>
    <div class="card">
      <h3>آخر الفواتير</h3>
      <div class="table-wrap"><table>
      <tr><th>الفاتورة</th><th>الإجمالي</th><th>التاريخ</th><th></th></tr>
      {% for s in recent %}
      <tr><td>{{s.invoice_no}}</td><td>{{s.total}}</td>
      <td>{{s.created_at}}</td>
      <td><a href="/invoice/{{s.id}}">عرض</a></td></tr>
      {% endfor %}
      </table></div>
    </div>
    """, sales=money(sales), cost=money(cost), expenses=money(expenses),
         net=money(net), products=products, low=low, recent=recent)


# =========================================================
# PRODUCTS
# =========================================================

@app.route("/products", methods=["GET", "POST"])
@roles("owner", "manager")
def products_page():
    con = db()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        image = request.form.get("image", "").strip()

        try:
            price = float(request.form.get("price", 0))
            cost = float(request.form.get("cost", 0))
            stock = float(request.form.get("stock", 0))
            low = float(request.form.get("low_stock", 5))
            if not name or min(price, cost, stock, low) < 0:
                raise ValueError()
        except ValueError:
            flash("تأكد من صحة الاسم والأسعار والكميات")
        else:
            con.execute("""
                INSERT INTO products(name,category,price,cost,stock,low_stock,image,created_at)
                VALUES(?,?,?,?,?,?,?,?)
            """, (name, category, price, cost, stock, low, image, now()))
            con.commit()
            product_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            if stock:
                con.execute("""
                    INSERT INTO stock_moves(product_id,quantity,reason,note,user_id,created_at)
                    VALUES(?,?,?,?,?,?)
                """, (product_id, stock, "رصيد افتتاحي", "", session["user_id"], now()))
                con.commit()
            log("add_product", name)
            flash("تمت إضافة المنتج")

    items = con.execute(
        "SELECT * FROM products WHERE active=1 ORDER BY id DESC"
    ).fetchall()
    con.close()

    return page("المنتجات", """
    <div class="card">
    <h3>إضافة منتج</h3>
    <form method="post">
    <div class="grid">
    <div><label>اسم المنتج</label><input name="name" required></div>
    <div><label>القسم</label><input name="category"></div>
    <div><label>سعر البيع</label><input name="price" type="number" step="0.01" min="0" required></div>
    <div><label>التكلفة</label><input name="cost" type="number" step="0.01" min="0" required></div>
    <div><label>الكمية</label><input name="stock" type="number" step="0.01" min="0" value="0"></div>
    <div><label>حد التنبيه</label><input name="low_stock" type="number" step="0.01" min="0" value="5"></div>
    </div>
    <label>رابط صورة المنتج (اختياري)</label><input name="image">
    <button>حفظ المنتج</button>
    </form></div>
    <div class="card"><h3>قائمة المنتجات</h3>
    <div class="table-wrap"><table>
    <tr><th>المنتج</th><th>القسم</th><th>السعر</th><th>التكلفة</th><th>المخزون</th><th>الحالة</th><th></th></tr>
    {% for p in items %}
    <tr>
    <td>{{p.name}}</td><td>{{p.category}}</td>
    <td>{{p.price}}</td><td>{{p.cost}}</td><td>{{p.stock}}</td>
    <td>{% if p.stock<=p.low_stock %}<span class="bad">منخفض</span>{% else %}جيد{% endif %}</td>
    <td><a href="/product/{{p.id}}/edit">تعديل</a></td>
    </tr>{% endfor %}
    </table></div></div>
    """, items=items)


@app.route("/product/<int:pid>/edit", methods=["GET", "POST"])
@roles("owner", "manager")
def edit_product(pid):
    con = db()
    p = con.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if not p:
        con.close()
        abort(404)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        try:
            price = float(request.form["price"])
            cost = float(request.form["cost"])
            low = float(request.form["low_stock"])
            if not name or min(price, cost, low) < 0:
                raise ValueError()
        except (ValueError, KeyError):
            flash("بيانات غير صحيحة")
        else:
            con.execute("""
                UPDATE products SET name=?,category=?,price=?,cost=?,low_stock=?,image=?
                WHERE id=?
            """, (name, category, price, cost, low,
                  request.form.get("image", "").strip(), pid))
            con.commit()
            con.close()
            log("edit_product", name)
            return redirect(url_for("products_page"))

    con.close()
    return page("تعديل منتج", """
    <div class="card"><form method="post">
    <label>الاسم</label><input name="name" value="{{p.name}}" required>
    <label>القسم</label><input name="category" value="{{p.category}}">
    <label>سعر البيع</label><input name="price" type="number" step=".01" value="{{p.price}}" required>
    <label>التكلفة</label><input name="cost" type="number" step=".01" value="{{p.cost}}" required>
    <label>حد المخزون المنخفض</label><input name="low_stock" type="number" step=".01" value="{{p.low_stock}}">
    <label>رابط الصورة</label><input name="image" value="{{p.image}}">
    <button>حفظ التعديلات</button>
    </form>
    <form method="post" action="/product/{{p.id}}/delete" onsubmit="return confirm('حذف المنتج؟')">
    <button class="btn-dark">إيقاف المنتج</button></form></div>
    """, p=p)


@app.route("/product/<int:pid>/delete", methods=["POST"])
@roles("owner", "manager")
def delete_product(pid):
    con = db()
    con.execute("UPDATE products SET active=0 WHERE id=?", (pid,))
    con.commit()
    con.close()
    log("deactivate_product", str(pid))
    return redirect(url_for("products_page"))


# =========================================================
# STOCK
# =========================================================

@app.route("/stock", methods=["GET", "POST"])
@roles("owner", "manager")
def stock_page():
    con = db()

    if request.method == "POST":
        try:
            pid = int(request.form["product_id"])
            qty = float(request.form["quantity"])
            reason = request.form.get("reason", "إضافة مخزون")
            note = request.form.get("note", "")
            if qty <= 0:
                raise ValueError()
            product = con.execute(
                "SELECT * FROM products WHERE id=? AND active=1", (pid,)
            ).fetchone()
            if not product:
                raise ValueError()

            con.execute("UPDATE products SET stock=stock+? WHERE id=?", (qty, pid))
            con.execute("""
                INSERT INTO stock_moves(product_id,quantity,reason,note,user_id,created_at)
                VALUES(?,?,?,?,?,?)
            """, (pid, qty, reason, note, session["user_id"], now()))
            con.commit()
            log("stock_in", f"{product['name']} +{qty}")
            flash("تم تحديث المخزون")
        except (ValueError, KeyError):
            flash("بيانات غير صحيحة")

    items = con.execute(
        "SELECT * FROM products WHERE active=1 ORDER BY name"
    ).fetchall()
    moves = con.execute("""
        SELECT m.*,p.name FROM stock_moves m
        JOIN products p ON p.id=m.product_id
        ORDER BY m.id DESC LIMIT 50
    """).fetchall()
    con.close()

    return page("إدارة المخزون", """
    <div class="card"><h3>إضافة كمية للمخزون</h3>
    <form method="post">
    <label>المنتج</label><select name="product_id" required>
    {% for p in items %}<option value="{{p.id}}">{{p.name}} - المتاح {{p.stock}}</option>{% endfor %}
    </select>
    <label>الكمية المضافة</label><input type="number" step=".01" min=".01" name="quantity" required>
    <label>السبب</label><input name="reason" value="شراء بضاعة">
    <label>ملاحظة</label><input name="note">
    <button>إضافة للمخزون</button></form></div>
    <div class="card"><h3>حركة المخزون</h3>
    <div class="table-wrap"><table>
    <tr><th>المنتج</th><th>الكمية</th><th>السبب</th><th>التاريخ</th></tr>
    {% for m in moves %}
    <tr><td>{{m.name}}</td><td>{{m.quantity}}</td><td>{{m.reason}}</td><td>{{m.created_at}}</td></tr>
    {% endfor %}</table></div></div>
    """, items=items, moves=moves)


# =========================================================
# POS / SALES
# =========================================================

@app.route("/pos", methods=["GET", "POST"])
@login_required
def pos():
    con = db()
    items = con.execute(
        "SELECT * FROM products WHERE active=1 AND stock>0 ORDER BY name"
    ).fetchall()
    tables = con.execute(
        "SELECT * FROM restaurant_tables ORDER BY id"
    ).fetchall()

    if request.method == "POST":
        try:
            pid = int(request.form["product_id"])
            qty = float(request.form["quantity"])
            discount = float(request.form.get("discount", 0))
            table_id = request.form.get("table_id") or None
            payment = request.form.get("payment_method", "cash")

            p = con.execute(
                "SELECT * FROM products WHERE id=? AND active=1", (pid,)
            ).fetchone()

            if not p or qty <= 0 or qty > p["stock"] or discount < 0:
                raise ValueError("الكمية أو المنتج غير صحيح")

            subtotal = p["price"] * qty
            total = subtotal - discount
            if total < 0:
                raise ValueError("الخصم أكبر من قيمة البيع")

            invoice = "YH-" + datetime.now().strftime("%y%m%d%H%M%S") + "-" + secrets.token_hex(2).upper()

            cur = con.execute("""
                INSERT INTO sales(invoice_no,total,discount,paid,payment_method,table_id,status,user_id,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)
            """, (invoice, total, discount, total, payment, table_id,
                  "completed", session["user_id"], now()))
            sale_id = cur.lastrowid

            con.execute("""
                INSERT INTO sale_items(sale_id,product_id,product_name,quantity,price,cost,subtotal)
                VALUES(?,?,?,?,?,?,?)
            """, (sale_id, pid, p["name"], qty, p["price"], p["cost"], subtotal))

            con.execute("UPDATE products SET stock=stock-? WHERE id=?", (qty, pid))

            con.execute("""
                INSERT INTO stock_moves(product_id,quantity,reason,note,user_id,created_at)
                VALUES(?,?,?,?,?,?)
            """, (pid, -qty, "بيع", invoice, session["user_id"], now()))

            if table_id:
                con.execute(
                    "UPDATE restaurant_tables SET status='occupied' WHERE id=?",
                    (table_id,)
                )

            con.commit()
            con.close()
            log("sale", invoice)
            return redirect(url_for("invoice", sid=sale_id))

        except (ValueError, KeyError) as e:
            flash(str(e) or "تعذر إتمام البيع")
            con.rollback()

    con.close()
    return page("نقطة البيع", """
    <div class="card">
    <h3>تسجيل عملية بيع</h3>
    <form method="post">
    <label>الصنف</label><select name="product_id" required>
    {% for p in items %}
    <option value="{{p.id}}">{{p.name}} | السعر {{p.price}} | المتوفر {{p.stock}}</option>
    {% endfor %}</select>
    <div class="grid">
    <div><label>الكمية</label><input name="quantity" type="number" min=".01" step=".01" value="1" required></div>
    <div><label>الخصم</label><input name="discount" type="number" min="0" step=".01" value="0"></div>
    <div><label>الطاولة (اختياري)</label>
    <select name="table_id"><option value="">سفري</option>
    {% for t in tables %}<option value="{{t.id}}">{{t.name}} - {{t.status}}</option>{% endfor %}
    </select></div>
    <div><label>طريقة الدفع</label><select name="payment_method">
    <option value="cash">نقدي</option><option value="card">بطاقة</option>
    <option value="bank">تحويل</option></select></div>
    </div>
    <button>إتمام البيع وطباعة الفاتورة</button>
    </form></div>
    <div class="alert">كل عملية بيع تخصم الكمية من المخزون تلقائياً. لإضافة عدة أصناف في فاتورة واحدة، يمكن تطوير السلة في واجهة لاحقة.</div>
    """, items=items, tables=tables)


@app.route("/invoice/<int:sid>")
@login_required
def invoice(sid):
    con = db()
    sale = con.execute("SELECT * FROM sales WHERE id=?", (sid,)).fetchone()
    if not sale:
        con.close()
        abort(404)
    items = con.execute(
        "SELECT * FROM sale_items WHERE sale_id=?", (sid,)
    ).fetchall()
    restaurant = setting("restaurant_name")
    footer = setting("receipt_footer")
    con.close()

    return page("الفاتورة " + sale["invoice_no"], """
    <div class="card" id="receipt" style="max-width:650px;margin:auto">
    <div style="text-align:center">
    <h1 style="color:#c92332">YH</h1>
    <h2>{{restaurant}}</h2>
    <h3>فاتورة بيع</h3>
    </div>
    <p>رقم الفاتورة: {{sale.invoice_no}}</p>
    <p>التاريخ: {{sale.created_at}}</p>
    <div class="table-wrap"><table>
    <tr><th>الصنف</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th></tr>
    {% for i in items %}
    <tr><td>{{i.product_name}}</td><td>{{i.quantity}}</td>
    <td>{{i.price}}</td><td>{{i.subtotal}}</td></tr>
    {% endfor %}
    </table></div>
    <h3>الخصم: {{sale.discount}}</h3>
    <h2>الإجمالي: {{sale.total}} {{currency}}</h2>
    <p style="text-align:center">{{footer}}</p>
    </div>
    <div style="text-align:center">
    <button onclick="window.print()">طباعة الفاتورة</button>
    <a class="btn btn-dark" href="/pos">بيع جديد</a>
    </div>
    <style>@media print {
    nav,header,footer,button,.btn,h2:first-of-type {display:none!important}
    body{background:white}main{padding:0}
    #receipt{box-shadow:none}
    }</style>
    """, sale=sale, items=items, restaurant=restaurant,
         footer=footer, currency=setting("currency"))


@app.route("/sales")
@login_required
def sales_page():
    con = db()
    items = con.execute(
        "SELECT * FROM sales ORDER BY id DESC LIMIT 300"
    ).fetchall()
    con.close()
    return page("سجل المبيعات", """
    <div class="card"><div class="table-wrap"><table>
    <tr><th>الفاتورة</th><th>الإجمالي</th><th>الخصم</th>
    <th>الدفع</th><th>التاريخ</th><th></th></tr>
    {% for s in items %}
    <tr><td>{{s.invoice_no}}</td><td>{{s.total}}</td><td>{{s.discount}}</td>
    <td>{{s.payment_method}}</td><td>{{s.created_at}}</td>
    <td><a href="/invoice/{{s.id}}">الفاتورة</a></td></tr>
    {% endfor %}</table></div></div>
    """, items=items)


# =========================================================
# TABLES / KITCHEN / ORDERS
# =========================================================

@app.route("/tables", methods=["GET", "POST"])
@roles("owner", "manager", "cashier")
def tables_page():
    con = db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            try:
                con.execute("INSERT INTO restaurant_tables(name) VALUES(?)", (name,))
                con.commit()
                flash("تمت إضافة الطاولة")
            except sqlite3.IntegrityError:
                flash("اسم الطاولة موجود مسبقاً")

    tables = con.execute("SELECT * FROM restaurant_tables ORDER BY id").fetchall()
    con.close()
    return page("الطاولات", """
    <div class="card"><form method="post">
    <label>إضافة طاولة</label><input name="name" required>
    <button>إضافة</button></form></div>
    <div class="grid">
    {% for t in tables %}
    <div class="card">
    <h3>{{t.name}}</h3><p>الحالة: {{t.status}}</p>
    <form method="post" action="/table/{{t.id}}/status">
    <select name="status">
    <option value="available">متاحة</option>
    <option value="occupied">مشغولة</option>
    <option value="reserved">محجوزة</option>
    </select><button>تحديث الحالة</button></form>
    </div>{% endfor %}</div>
    """, tables=tables)


@app.route("/table/<int:tid>/status", methods=["POST"])
@roles("owner", "manager", "cashier")
def table_status(tid):
    status = request.form.get("status")
    if status not in ("available", "occupied", "reserved"):
        abort(400)
    con = db()
    con.execute(
        "UPDATE restaurant_tables SET status=? WHERE id=?", (status, tid)
    )
    con.commit()
    con.close()
    log("table_status", f"{tid}: {status}")
    return redirect(url_for("tables_page"))


@app.route("/kitchen")
@login_required
def kitchen():
    con = db()
    orders = con.execute("""
        SELECT s.*,t.name AS table_name
        FROM sales s LEFT JOIN restaurant_tables t ON t.id=s.table_id
        WHERE s.status IN ('pending','preparing','ready')
        ORDER BY s.id
    """).fetchall()
    con.close()
    return page("شاشة المطبخ", """
    <div class="grid">
    {% for o in orders %}
    <div class="card">
    <h3>{{o.invoice_no}}</h3>
    <p>الطاولة: {{o.table_name or 'سفري'}}</p>
    <p>الحالة: {{o.status}}</p>
    <a class="btn" href="/invoice/{{o.id}}">تفاصيل الطلب</a>
    <form method="post" action="/order/{{o.id}}/status">
    <select name="status">
    <option value="preparing">قيد التجهيز</option>
    <option value="ready">جاهز</option>
    <option value="completed">مكتمل</option>
    </select><button>تحديث</button></form>
    </div>
    {% else %}<div class="card">لا توجد طلبات معلقة.</div>{% endfor %}
    </div>
    """, orders=orders)


@app.route("/orders")
@login_required
def orders():
    con = db()
    items = con.execute(
        "SELECT * FROM sales ORDER BY id DESC LIMIT 200"
    ).fetchall()
    con.close()
    return page("الطلبات", """
    <div class="card"><div class="table-wrap"><table>
    <tr><th>رقم</th><th>الحالة</th><th>الإجمالي</th><th>التاريخ</th><th></th></tr>
    {% for o in items %}
    <tr><td>{{o.invoice_no}}</td><td>{{o.status}}</td><td>{{o.total}}</td>
    <td>{{o.created_at}}</td><td><a href="/invoice/{{o.id}}">عرض</a></td></tr>
    {% endfor %}</table></div></div>
    """, items=items)


@app.route("/order/<int:sid>/status", methods=["POST"])
@roles("owner", "manager", "cashier")
def order_status(sid):
    status = request.form.get("status")
    if status not in ("pending", "preparing", "ready", "completed"):
        abort(400)
    con = db()
    con.execute("UPDATE sales SET status=? WHERE id=?", (status, sid))
    con.commit()
    con.close()
    log("order_status", f"{sid}: {status}")
    return redirect(url_for("kitchen"))


# =========================================================
# EXPENSES
# =========================================================

@app.route("/expenses", methods=["GET", "POST"])
@roles("owner", "manager")
def expenses_page():
    con = db()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        note = request.form.get("note", "")
        try:
            amount = float(request.form["amount"])
            if not title or amount <= 0:
                raise ValueError()
            con.execute("""
                INSERT INTO expenses(title,category,amount,note,user_id,created_at)
                VALUES(?,?,?,?,?,?)
            """, (title, category, amount, note, session["user_id"], now()))
            con.commit()
            log("expense", f"{title}: {amount}")
            flash("تم تسجيل المصروف")
        except (ValueError, KeyError):
            flash("أدخل بيانات صحيحة")

    items = con.execute(
        "SELECT * FROM expenses ORDER BY id DESC LIMIT 300"
    ).fetchall()
    con.close()
    return page("المصروفات", """
    <div class="card"><form method="post">
    <div class="grid">
    <div><label>اسم المصروف</label><input name="title" required></div>
    <div><label>التصنيف</label><input name="category" placeholder="إيجار، كهرباء، رواتب..."></div>
    <div><label>المبلغ</label><input name="amount" type="number" min=".01" step=".01" required></div>
    </div>
    <label>ملاحظات</label><input name="note">
    <button>حفظ المصروف</button></form></div>
    <div class="card"><div class="table-wrap"><table>
    <tr><th>المصروف</th><th>التصنيف</th><th>المبلغ</th><th>التاريخ</th></tr>
    {% for e in items %}
    <tr><td>{{e.title}}</td><td>{{e.category}}</td><td>{{e.amount}}</td><td>{{e.created_at}}</td></tr>
    {% endfor %}</table></div></div>
    """, items=items)


# =========================================================
# REPORTS
# =========================================================

@app.route("/reports")
@roles("owner", "manager")
def reports():
    start = request.args.get("start", datetime.now().strftime("%Y-%m-01"))
    end = request.args.get("end", datetime.now().strftime("%Y-%m-%d"))

    con = db()
    sales = con.execute("""
        SELECT COALESCE(SUM(total),0) FROM sales
        WHERE status='completed' AND substr(created_at,1,10) BETWEEN ? AND ?
    """, (start, end)).fetchone()[0]

    cost = con.execute("""
        SELECT COALESCE(SUM(si.quantity*si.cost),0)
        FROM sale_items si JOIN sales s ON s.id=si.sale_id
        WHERE s.status='completed' AND substr(s.created_at,1,10) BETWEEN ? AND ?
    """, (start, end)).fetchone()[0]

    expenses = con.execute("""
        SELECT COALESCE(SUM(amount),0) FROM expenses
        WHERE substr(created_at,1,10) BETWEEN ? AND ?
    """, (start, end)).fetchone()[0]

    daily = con.execute("""
        SELECT substr(created_at,1,10) AS day, SUM(total) AS amount
        FROM sales WHERE status='completed'
        AND substr(created_at,1,10) BETWEEN ? AND ?
        GROUP BY day ORDER BY day
    """, (start, end)).fetchall()

    top = con.execute("""
        SELECT product_name,SUM(quantity) AS qty,
        SUM(subtotal) AS amount
        FROM sale_items si JOIN sales s ON s.id=si.sale_id
        WHERE s.status='completed'
        AND substr(s.created_at,1,10) BETWEEN ? AND ?
        GROUP BY product_name ORDER BY qty DESC LIMIT 10
    """, (start, end)).fetchall()

    con.close()
    gross = sales - cost
    net = gross - expenses

    return page("التقارير والأرباح", """
    <div class="card"><form method="get">
    <div class="grid">
    <div><label>من تاريخ</label><input type="date" name="start" value="{{start}}"></div>
    <div><label>إلى تاريخ</label><input type="date" name="end" value="{{end}}"></div>
    </div><button>عرض التقرير</button></form></div>
    <div class="grid">
    <div class="card stat"><h3>المبيعات</h3><strong>{{sales}}</strong></div>
    <div class="card stat"><h3>تكلفة البضاعة</h3><strong>{{cost}}</strong></div>
    <div class="card stat"><h3>مجمل الربح</h3><strong>{{gross}}</strong></div>
    <div class="card stat"><h3>المصروفات</h3><strong>{{expenses}}</strong></div>
    <div class="card stat"><h3>صافي الربح</h3><strong>{{net}}</strong></div>
    </div>
    <div class="card"><h3>المبيعات اليومية</h3>
    {% for d in daily %}
      <p>{{d.day}} — {{d.amount}} {{currency}}</p>
      <div style="height:12px;background:#eee;border-radius:10px;overflow:hidden">
      <div style="height:12px;background:#c92332;width:{{(d.amount/max_sale*100) if max_sale else 0}}%"></div>
      </div>
    {% endfor %}</div>
    <div class="card"><h3>الأصناف الأكثر مبيعاً</h3>
    <table><tr><th>الصنف</th><th>الكمية</th><th>المبيعات</th></tr>
    {% for p in top %}<tr><td>{{p.product_name}}</td><td>{{p.qty}}</td><td>{{p.amount}}</td></tr>{% endfor %}
    </table></div>
    """, start=start, end=end, sales=money(sales), cost=money(cost),
         gross=money(gross), expenses=money(expenses), net=money(net),
         daily=daily, top=top, currency=setting("currency"),
         max_sale=max([d["amount"] for d in daily], default=0))


# =========================================================
# USERS / EMPLOYEES
# =========================================================

@app.route("/users", methods=["GET", "POST"])
@roles("owner", "manager")
def users_page():
    user = current_user()
    con = db()

    if request.method == "POST":
        if user["role"] != "owner":
            abort(403)

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "cashier")

        if role not in ("manager", "cashier"):
            flash("الدور غير صحيح")
        elif not name or not email or len(password) < 8:
            flash("أدخل بيانات صحيحة وكلمة مرور من 8 أحرف على الأقل")
        else:
            try:
                con.execute("""
                    INSERT INTO users(name,email,password,role,created_at)
                    VALUES(?,?,?,?,?)
                """, (name, email, generate_password_hash(password), role, now()))
                con.commit()
                log("add_user", email)
                flash("تم إنشاء حساب الموظف")
            except sqlite3.IntegrityError:
                flash("هذا البريد مسجل مسبقاً")

    users = con.execute(
        "SELECT id,name,email,role,active,created_at FROM users ORDER BY id"
    ).fetchall()
    con.close()

    return page("الموظفون والصلاحيات", """
    {% if user.role=='owner' %}
    <div class="card"><h3>إضافة موظف</h3>
    <form method="post">
    <label>الاسم</label><input name="name" required>
    <label>البريد</label><input type="email" name="email" required>
    <label>كلمة المرور</label><input type="password" name="password" minlength="8" required>
    <label>الصلاحية</label><select name="role">
    <option value="cashier">كاشير</option><option value="manager">مدير</option>
    </select><button>إنشاء الحساب</button>
    </form></div>{% endif %}
    <div class="card"><div class="table-wrap"><table>
    <tr><th>الاسم</th><th>البريد</th><th>الصلاحية</th><th>الحالة</th><th></th></tr>
    {% for u in users %}
    <tr><td>{{u.name}}</td><td>{{u.email}}</td><td>{{u.role}}</td>
    <td>{{'نشط' if u.active else 'موقوف'}}</td>
    <td>{% if user.role=='owner' and u.id!=user.id %}
    <form method="post" action="/user/{{u.id}}/toggle">
    <button class="btn-dark">{{'إيقاف' if u.active else 'تفعيل'}}</button>
    </form>{% endif %}</td></tr>
    {% endfor %}</table></div></div>
    """, users=users, user=user)


@app.route("/user/<int:uid>/toggle", methods=["POST"])
@roles("owner")
def toggle_user(uid):
    if uid == session["user_id"]:
        flash("لا يمكنك إيقاف حسابك الحالي")
        return redirect(url_for("users_page"))

    con = db()
    con.execute("UPDATE users SET active=1-active WHERE id=?", (uid,))
    con.commit()
    con.close()
    log("toggle_user", str(uid))
    return redirect(url_for("users_page"))


# =========================================================
# CHANGE PASSWORD BY EMAIL OTP
# =========================================================

def send_email(to, subject, body):
    host = setting("email_host")
    port = int(setting("email_port", "587"))
    username = setting("email_user")
    password = setting("email_password")
    sender = setting("email_from") or username

    if not host or not username or not password or not sender:
        raise RuntimeError("إعدادات البريد غير مكتملة")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=20) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(msg)


@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        con = db()
        user = con.execute(
            "SELECT * FROM users WHERE email=? AND active=1", (email,)
        ).fetchone()

        if user:
            code = f"{secrets.randbelow(1000000):06d}"
            expires = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
            con.execute(
                "INSERT INTO password_resets(user_id,code,expires_at) VALUES(?,?,?)",
                (user["id"], code, expires)
            )
            con.commit()
            con.close()
            try:
                send_email(email, "YH Password Verification",
                           f"رمز التحقق الخاص بك هو: {code}\nصالح لمدة 10 دقائق.")
                flash("إذا كان البريد مسجلاً، فقد تم إرسال رمز التحقق إليه.")
                return redirect(url_for("verify_code", email=email))
            except Exception:
                flash("تعذر إرسال البريد. راجع إعدادات SMTP والاتصال.")
                return redirect(url_for("forgot"))

        con.close()
        flash("إذا كان البريد مسجلاً، فستصلك تعليمات الاستعادة.")

    return page("استعادة كلمة المرور", """
    <div class="card"><form method="post">
    <label>البريد الإلكتروني المسجل</label>
    <input type="email" name="email" required>
    <button>إرسال رمز التحقق</button></form></div>
    """)


@app.route("/verify", methods=["GET", "POST"])
def verify_code():
    email = request.args.get("email", "")
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        code = request.form.get("code", "").strip()
        password = request.form.get("password", "")

        if len(password) < 8:
            flash("كلمة المرور يجب ألا تقل عن 8 أحرف")
            return redirect(url_for("verify_code", email=email))

        con = db()
        row = con.execute("""
            SELECT pr.*,u.email FROM password_resets pr
            JOIN users u ON u.id=pr.user_id
            WHERE u.email=? AND pr.code=? AND pr.used=0
            ORDER BY pr.id DESC LIMIT 1
        """, (email, code)).fetchone()

        if row and row["expires_at"] >= now():
            con.execute(
                "UPDATE users SET password=? WHERE id=?",
                (generate_password_hash(password), row["user_id"])
            )
            con.execute(
                "UPDATE password_resets SET used=1 WHERE id=?", (row["id"],)
            )
            con.commit()
            con.close()
            flash("تم تغيير كلمة المرور. سجل الدخول.")
            return redirect(url_for("login"))

        con.close()
        flash("الرمز غير صحيح أو انتهت صلاحيته")

    return page("التحقق من رمز البريد", """
    <div class="card"><form method="post">
    <label>البريد الإلكتروني</label>
    <input type="email" name="email" value="{{email}}" required>
    <label>رمز التحقق المرسل إلى بريدك</label>
    <input name="code" maxlength="6" required>
    <label>كلمة المرور الجديدة</label>
    <input type="password" name="password" minlength="8" required>
    <button>تأكيد وتغيير كلمة المرور</button></form></div>
    """, email=email)


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old = request.form.get("old", "")
        new = request.form.get("new", "")
        con = db()
        user = con.execute(
            "SELECT * FROM users WHERE id=?", (session["user_id"],)
        ).fetchone()

        if not check_password_hash(user["password"], old):
            flash("كلمة المرور الحالية غير صحيحة")
        elif len(new) < 8:
            flash("كلمة المرور الجديدة يجب ألا تقل عن 8 أحرف")
        else:
            con.execute(
                "UPDATE users SET password=? WHERE id=?",
                (generate_password_hash(new), user["id"])
            )
            con.commit()
            log("change_password", "تغيير كلمة المرور")
            flash("تم تغيير كلمة المرور")
            con.close()
            return redirect(url_for("dashboard"))
        con.close()

    return page("تغيير كلمة المرور", """
    <div class="card"><form method="post">
    <label>كلمة المرور الحالية</label><input name="old" type="password" required>
    <label>كلمة المرور الجديدة</label><input name="new" type="password" minlength="8" required>
    <button>حفظ كلمة المرور</button></form></div>
    """)


# =========================================================
# SETTINGS
# =========================================================

@app.route("/settings", methods=["GET", "POST"])
@roles("owner")
def settings_page():
    con = db()

    if request.method == "POST":
        keys = [
            "restaurant_name", "currency", "primary_color",
            "secondary_color", "email_host", "email_port",
            "email_user", "email_password", "email_from",
            "receipt_footer"
        ]
        for key in keys:
            value = request.form.get(key, "").strip()
            con.execute("""
                INSERT INTO settings(key,value) VALUES(?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """, (key, value))
        con.commit()
        log("settings_update", "تحديث إعدادات النظام")
        flash("تم حفظ الإعدادات")

    con.close()

    return page("إعدادات المطعم", """
    <div class="card"><form method="post">
    <h3>بيانات المطعم</h3>
    <label>اسم المطعم</label><input name="restaurant_name" value="{{v.restaurant_name}}">
    <label>العملة</label><input name="currency" value="{{v.currency}}">
    <label>لون الواجهة الأساسي</label><input type="color" name="primary_color" value="{{v.primary_color}}">
    <label>اللون الثانوي</label><input type="color" name="secondary_color" value="{{v.secondary_color}}">
    <label>نص أسفل الفاتورة</label><input name="receipt_footer" value="{{v.receipt_footer}}">
    <hr><h3>إعدادات البريد SMTP</h3>
    <label>SMTP Host</label><input name="email_host" value="{{v.email_host}}" placeholder="smtp.gmail.com">
    <label>SMTP Port</label><input name="email_port" value="{{v.email_port}}" placeholder="587">
    <label>البريد المرسل</label><input name="email_user" value="{{v.email_user}}">
    <label>كلمة مرور التطبيق</label><input name="email_password" type="password" value="{{v.email_password}}">
    <label>عنوان From</label><input name="email_from" value="{{v.email_from}}">
    <button>حفظ الإعدادات</button>
    </form>
    <p><a href="/change-password">تغيير كلمة المرور من داخل النظام</a></p>
    </div>
    <script>
    document.querySelector('input[name="primary_color"]').addEventListener('input',e=>{
      document.documentElement.style.setProperty('--red',e.target.value);
    });
    </script>
    """, v={
        "restaurant_name": setting("restaurant_name"),
        "currency": setting("currency"),
        "primary_color": setting("primary_color"),
        "secondary_color": setting("secondary_color"),
        "email_host": setting("email_host"),
        "email_port": setting("email_port"),
        "email_user": setting("email_user"),
        "email_password": setting("email_password"),
        "email_from": setting("email_from"),
        "receipt_footer": setting("receipt_footer")
    })


# =========================================================
# AUDIT LOGS
# =========================================================

@app.route("/logs")
@roles("owner", "manager")
def logs_page():
    con = db()
    rows = con.execute("""
        SELECT a.*,u.name FROM audit_logs a
        LEFT JOIN users u ON u.id=a.user_id
        ORDER BY a.id DESC LIMIT 500
    """).fetchall()
    con.close()

    return page("سجل العمليات", """
    <div class="card"><div class="table-wrap"><table>
    <tr><th>المستخدم</th><th>العملية</th><th>التفاصيل</th><th>التاريخ</th></tr>
    {% for r in rows %}
    <tr><td>{{r.name or 'غير معروف'}}</td><td>{{r.action}}</td>
    <td>{{r.details}}</td><td>{{r.created_at}}</td></tr>
    {% endfor %}</table></div></div>
    """, rows=rows)


# =========================================================
# BACKUP / RESTORE
# =========================================================

@app.route("/backup")
@roles("owner")
def backup():
    if not os.path.exists(DB_PATH):
        abort(404)
    filename = "YH_Restaurant_Backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".db"
    return send_file(DB_PATH, as_attachment=True, download_name=filename)


@app.route("/restore", methods=["POST"])
@roles("owner")
def restore():
    file = request.files.get("backup_file")
    if not file or not file.filename.lower().endswith(".db"):
        flash("اختر ملف نسخة احتياطية بصيغة DB")
        return redirect(url_for("backup_page"))

    temp_path = DB_PATH + ".restore"
    try:
        file.save(temp_path)
        test = sqlite3.connect(temp_path)
        result = test.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]
        test.close()

        if result != "ok":
            raise ValueError("قاعدة البيانات غير سليمة")

        # Keep a copy of the current database before restoring.
        shutil.copy2(DB_PATH, DB_PATH + ".before_restore")
        os.replace(temp_path, DB_PATH)
        session.clear()
        return redirect(url_for("login"))

    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        flash("فشلت الاستعادة: " + str(e))
        return redirect(url_for("backup_page"))


@app.route("/backup-page")
@roles("owner")
def backup_page():
    return page("النسخ الاحتياطي والاستعادة", """
    <div class="card">
    <h3>إنشاء نسخة احتياطية</h3>
    <p>احفظ نسخة من قاعدة البيانات على جهازك.</p>
    <a class="btn" href="/backup">تنزيل النسخة الاحتياطية</a>
    </div>
    <div class="card">
    <h3>استعادة نسخة سابقة</h3>
    <p>سيتم الاحتفاظ بنسخة من قاعدة البيانات الحالية قبل الاستعادة.</p>
    <form method="post" action="/restore" enctype="multipart/form-data"
    onsubmit="return confirm('هل تريد استعادة النسخة؟')">
    <input type="file" name="backup_file" accept=".db" required>
    <button>استعادة النسخة</button>
    </form></div>
    """)


# Redirect backup navigation to the backup page
@app.route("/backup-menu")
@login_required
def backup_menu():
    return redirect(url_for("backup_page"))


# =========================================================
# ERROR HANDLERS
# =========================================================

@app.errorhandler(403)
def forbidden(e):
    return page("غير مسموح", """
    <div class="card"><h3>ليس لديك صلاحية للوصول إلى هذه الصفحة.</h3>
    <a href="/">العودة للرئيسية</a></div>
    """), 403


@app.errorhandler(404)
def not_found(e):
    return page("الصفحة غير موجودة", """
    <div class="card"><h3>الصفحة المطلوبة غير موجودة.</h3>
    <a href="/">العودة للرئيسية</a></div>
    """), 404


@app.errorhandler(500)
def server_error(e):
    return page("حدث خطأ", """
    <div class="card"><h3>حدث خطأ داخلي. راجع شاشة التشغيل لمعرفة التفاصيل.</h3>
    <a href="/">العودة للرئيسية</a></div>
    """), 500


# =========================================================
# START
# =========================================================

init_db()

if __name__ == "__main__":
    print("YH RESTAURANT MANAGEMENT SYSTEM")
    app.run(host="0.0.0.0", port=5000, debug=False)
