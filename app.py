import os
import sqlite3
from datetime import date
from functools import wraps

from flask import (Flask, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    isbn TEXT NOT NULL UNIQUE,
    copies INTEGER NOT NULL DEFAULT 1 CHECK (copies >= 0),
    available INTEGER NOT NULL DEFAULT 1 CHECK (available >= 0)
);
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    roll_no TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id),
    student_id INTEGER NOT NULL REFERENCES students(id),
    issue_date TEXT NOT NULL,
    return_date TEXT
);
"""


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
        DATABASE=os.environ.get("DATABASE", os.path.join(BASE_DIR, "library.db")),
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME", "admin"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", "admin123"),
    )
    if test_config:
        app.config.update(test_config)

    # ---------- database helpers ----------
    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def init_db():
        db = sqlite3.connect(app.config["DATABASE"])
        db.executescript(SCHEMA)
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            db.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (app.config["ADMIN_USERNAME"],
                 generate_password_hash(app.config["ADMIN_PASSWORD"])),
            )
        db.commit()
        db.close()

    init_db()

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    # ---------- auth ----------
    @app.route("/")
    def index():
        return redirect(url_for("dashboard" if "user_id" in session else "login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = get_db().execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
            if user and check_password_hash(user["password_hash"], password):
                session.clear()
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                return redirect(url_for("dashboard"))
            flash("Wrong username or password. Check both and try again.", "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ---------- dashboard ----------
    @app.route("/dashboard")
    @login_required
    def dashboard():
        db = get_db()
        stats = {
            "titles": db.execute("SELECT COUNT(*) FROM books").fetchone()[0],
            "students": db.execute("SELECT COUNT(*) FROM students").fetchone()[0],
            "issued": db.execute(
                "SELECT COUNT(*) FROM issues WHERE return_date IS NULL").fetchone()[0],
            "available": db.execute(
                "SELECT COALESCE(SUM(available), 0) FROM books").fetchone()[0],
        }
        active = db.execute(
            """SELECT issues.id, issues.issue_date, books.title,
                      students.name, students.roll_no
               FROM issues
               JOIN books ON books.id = issues.book_id
               JOIN students ON students.id = issues.student_id
               WHERE issues.return_date IS NULL
               ORDER BY issues.issue_date""").fetchall()
        return render_template("dashboard.html", stats=stats, active=active)

    # ---------- books ----------
    @app.route("/books", methods=["GET", "POST"])
    @login_required
    def books():
        db = get_db()
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            author = request.form.get("author", "").strip()
            isbn = request.form.get("isbn", "").strip()
            try:
                copies = int(request.form.get("copies", "1"))
            except ValueError:
                copies = 0
            if not (title and author and isbn) or copies < 1:
                flash("Enter a title, author, ISBN and at least 1 copy.", "error")
            else:
                try:
                    db.execute(
                        "INSERT INTO books (title, author, isbn, copies, available) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (title, author, isbn, copies, copies))
                    db.commit()
                    flash(f"Added “{title}”.", "ok")
                except sqlite3.IntegrityError:
                    flash("A book with that ISBN already exists.", "error")
            return redirect(url_for("books"))
        rows = db.execute("SELECT * FROM books ORDER BY title").fetchall()
        students = db.execute("SELECT * FROM students ORDER BY name").fetchall()
        return render_template("books.html", books=rows, students=students)

    @app.route("/books/<int:book_id>/delete", methods=["POST"])
    @login_required
    def delete_book(book_id):
        db = get_db()
        out = db.execute(
            "SELECT COUNT(*) FROM issues WHERE book_id = ? AND return_date IS NULL",
            (book_id,)).fetchone()[0]
        if out:
            flash("This book has copies on loan. Return them before deleting.", "error")
        else:
            db.execute("DELETE FROM issues WHERE book_id = ?", (book_id,))
            db.execute("DELETE FROM books WHERE id = ?", (book_id,))
            db.commit()
            flash("Book deleted.", "ok")
        return redirect(url_for("books"))

    @app.route("/books/<int:book_id>/issue", methods=["POST"])
    @login_required
    def issue_book(book_id):
        db = get_db()
        student_id = request.form.get("student_id", type=int)
        book = db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        student = db.execute(
            "SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if not book or not student:
            flash("Choose a student to issue the book to.", "error")
        elif book["available"] < 1:
            flash("No copies of this book are available right now.", "error")
        else:
            db.execute(
                "INSERT INTO issues (book_id, student_id, issue_date) VALUES (?, ?, ?)",
                (book_id, student_id, date.today().isoformat()))
            db.execute(
                "UPDATE books SET available = available - 1 WHERE id = ?", (book_id,))
            db.commit()
            flash(f"Issued “{book['title']}” to {student['name']}.", "ok")
        return redirect(url_for("books"))

    @app.route("/issues/<int:issue_id>/return", methods=["POST"])
    @login_required
    def return_book(issue_id):
        db = get_db()
        issue = db.execute(
            "SELECT * FROM issues WHERE id = ? AND return_date IS NULL",
            (issue_id,)).fetchone()
        if issue:
            db.execute("UPDATE issues SET return_date = ? WHERE id = ?",
                       (date.today().isoformat(), issue_id))
            db.execute("UPDATE books SET available = available + 1 WHERE id = ?",
                       (issue["book_id"],))
            db.commit()
            flash("Book returned.", "ok")
        else:
            flash("That loan was already closed.", "error")
        return redirect(url_for("dashboard"))

    # ---------- students ----------
    @app.route("/students", methods=["GET", "POST"])
    @login_required
    def students():
        db = get_db()
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            roll_no = request.form.get("roll_no", "").strip()
            email = request.form.get("email", "").strip()
            if not (name and roll_no and email):
                flash("Enter a name, roll number and email.", "error")
            else:
                try:
                    db.execute(
                        "INSERT INTO students (name, roll_no, email) VALUES (?, ?, ?)",
                        (name, roll_no, email))
                    db.commit()
                    flash(f"Added {name}.", "ok")
                except sqlite3.IntegrityError:
                    flash("That roll number or email is already registered.", "error")
            return redirect(url_for("students"))
        rows = db.execute(
            """SELECT students.*,
                      (SELECT COUNT(*) FROM issues
                        WHERE issues.student_id = students.id
                          AND issues.return_date IS NULL) AS on_loan
               FROM students ORDER BY name""").fetchall()
        return render_template("students.html", students=rows)

    @app.route("/students/<int:student_id>/delete", methods=["POST"])
    @login_required
    def delete_student(student_id):
        db = get_db()
        out = db.execute(
            "SELECT COUNT(*) FROM issues WHERE student_id = ? AND return_date IS NULL",
            (student_id,)).fetchone()[0]
        if out:
            flash("This student still has books on loan.", "error")
        else:
            db.execute("DELETE FROM issues WHERE student_id = ?", (student_id,))
            db.execute("DELETE FROM students WHERE id = ?", (student_id,))
            db.commit()
            flash("Student deleted.", "ok")
        return redirect(url_for("students"))

    # ---------- search ----------
    @app.route("/search")
    @login_required
    def search():
        q = request.args.get("q", "").strip()
        scope = request.args.get("scope", "books")
        results = []
        if q:
            like = f"%{q}%"
            db = get_db()
            if scope == "students":
                results = db.execute(
                    "SELECT * FROM students WHERE name LIKE ? OR roll_no LIKE ? "
                    "OR email LIKE ? ORDER BY name", (like, like, like)).fetchall()
            else:
                scope = "books"
                results = db.execute(
                    "SELECT * FROM books WHERE title LIKE ? OR author LIKE ? "
                    "OR isbn LIKE ? ORDER BY title", (like, like, like)).fetchall()
        return render_template("search.html", q=q, scope=scope, results=results)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
