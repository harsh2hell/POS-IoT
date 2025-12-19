from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, session
)
import sqlite3
from datetime import datetime
import json
import qrcode
from io import BytesIO
import base64
import urllib.parse
from PIL import Image
import os
from functools import wraps

# =====================
# APP SETUP
# =====================

app = Flask(__name__)
app.secret_key = "pos_secret_key_2025"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "shop.db")

# =====================
# DATABASE HELPERS
# =====================

def get_db():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price REAL NOT NULL,
        category TEXT,
        available INTEGER DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS suggestions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item TEXT,
        customer TEXT,
        rating INTEGER,
        comments TEXT,
        date TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT,
        subtotal REAL,
        gst REAL,
        total REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS invoice_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER,
        name TEXT,
        price REAL,
        quantity INTEGER,
        line_total REAL
    )
    """)

    conn.commit()
    conn.close()

# 🔒 GUARANTEED DB INIT (THIS FIXES EVERYTHING)
with app.app_context():
    init_db()

# =====================
# AUTH DECORATOR
# =====================

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("staff_logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

# =====================
# AUTH ROUTES
# =====================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == "HarshX" and password == "harsh2hell":
            session["staff_logged_in"] = True
            return redirect(url_for("dashboard"))

        # 👇 NO FLASH
        return render_template(
            "login.html",
            error="Invalid email or password"
        )

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("menu"))

# =====================
# CUSTOMER ROUTES
# =====================

@app.route("/")
def home():
    return redirect(url_for("menu"))

@app.route("/menu")
def menu():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT name, price, available, category FROM items")
    items = cur.fetchall()
    conn.close()
    return render_template("menu.html", items=items)

# =====================
# STAFF ROUTES
# =====================

@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        cur.execute(
            "INSERT INTO items (name, price, category, available) VALUES (?, ?, ?, ?)",
            (
                request.form["name"],
                float(request.form["price"]),
                request.form.get("category"),
                1 if request.form.get("available") else 0,
            ),
        )
        conn.commit()
        flash("Item added")

    cur.execute("SELECT id, name, price, category, available FROM items")
    items = cur.fetchall()

    cur.execute("SELECT item, customer, rating, comments, date FROM suggestions ORDER BY id DESC")
    suggestions = cur.fetchall()

    conn.close()
    return render_template("index.html", items=items, suggestions=suggestions)

@app.route("/delete_item/<int:item_id>", methods=["POST"])
@login_required
def delete_item(item_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    flash("Item deleted")
    return redirect(url_for("dashboard"))

# =====================
# BILLING & QR
# =====================

@app.route("/generate_qr", methods=["POST"])
def generate_qr():
    cart = json.loads(request.form.get("cart", "[]"))

    conn = get_db()
    cur = conn.cursor()

    invoice_items = []
    subtotal = 0

    for item in cart:
        cur.execute("SELECT price FROM items WHERE name = ?", (item["name"],))
        row = cur.fetchone()
        if row:
            price = row[0]
            line_total = price * item["quantity"]
            subtotal += line_total
            invoice_items.append({
                "name": item["name"],
                "quantity": item["quantity"],
                "line_total": line_total
            })

    gst = round(subtotal * 0.18, 2)
    total = round(subtotal + gst, 2)

    cur.execute(
        "INSERT INTO invoices (created_at, subtotal, gst, total) VALUES (?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M"), subtotal, gst, total),
    )
    invoice_id = cur.lastrowid

    for i in invoice_items:
        cur.execute(
            "INSERT INTO invoice_items (invoice_id, name, price, quantity, line_total) VALUES (?, ?, ?, ?, ?)",
            (invoice_id, i["name"], 0, i["quantity"], i["line_total"]),
        )

    conn.commit()
    conn.close()

    params = {
        "pa": "9027775828@superyes",
        "pn": "Doon Mart",
        "am": f"{total:.2f}",
        "cu": "INR",
    }

    link = "upi://pay?" + urllib.parse.urlencode(params)
    qr = qrcode.make(link)

    buf = BytesIO()
    qr.save(buf, "PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    return render_template(
        "qr.html",
        qr_data=f"data:image/png;base64,{qr_b64}",
        invoice_lines=invoice_items,
        subtotal=subtotal,
        gst=gst,
        total=total,
        invoice_id=invoice_id
    )

# =====================
# INVOICE
# =====================

@app.route("/invoice/<int:invoice_id>")
def invoice(invoice_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id, created_at, subtotal, gst, total FROM invoices WHERE id = ?", (invoice_id,))
    invoice = cur.fetchone()

    cur.execute("SELECT name, price, quantity, line_total FROM invoice_items WHERE invoice_id = ?", (invoice_id,))
    items = cur.fetchall()

    conn.close()

    return render_template("invoice.html", invoice={
        "id": invoice[0],
        "created_at": invoice[1],
        "subtotal": invoice[2],
        "gst": invoice[3],
        "total": invoice[4]
    }, items=items)

# =====================
# FEEDBACK
# =====================

@app.route("/suggest_page")
def suggest_page():
    return render_template("suggest.html")


@app.route("/suggest", methods=["POST"])
def suggest():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO suggestions (item, customer, rating, comments, date) VALUES (?, ?, ?, ?, ?)",
        (
            request.form["item"],
            request.form.get("customer"),
            request.form.get("rating"),
            request.form.get("comments"),
            datetime.now().strftime("%Y-%m-%d"),
        ),
    )
    conn.commit()
    conn.close()
    flash("Thanks for feedback")
    return redirect(url_for("menu"))

# =====================
# RUN
# =====================

if __name__ == "__main__":
    app.run(debug=True)
