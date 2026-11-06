import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test.db"),
        "SECRET_KEY": "test",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "secret",
    })
    return app.test_client()


def login(client, password="secret"):
    return client.post("/login", data={"username": "admin", "password": password},
                       follow_redirects=True)


def add_book(client, isbn="111", copies="2"):
    return client.post("/books", data={"title": "Clean Code", "author": "Robert Martin",
                                       "isbn": isbn, "copies": copies},
                       follow_redirects=True)


def add_student(client):
    return client.post("/students", data={"name": "Asha", "roll_no": "R1",
                                          "email": "asha@example.com"},
                       follow_redirects=True)


def test_requires_login(client):
    r = client.get("/dashboard")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_login_success_and_failure(client):
    assert b"Dashboard" in login(client).data
    client.get("/logout")
    assert b"Wrong username or password" in login(client, "nope").data


def test_add_book_and_duplicate_isbn(client):
    login(client)
    assert b"Clean Code" in add_book(client).data
    assert b"already exists" in add_book(client).data


def test_add_student(client):
    login(client)
    assert b"asha@example.com" in add_student(client).data


def test_issue_and_return_flow(client):
    login(client)
    add_book(client, copies="1")
    add_student(client)
    r = client.post("/books/1/issue", data={"student_id": 1}, follow_redirects=True)
    assert b"Issued" in r.data
    r = client.post("/books/1/issue", data={"student_id": 1}, follow_redirects=True)
    assert b"No copies" in r.data
    r = client.post("/books/1/delete", follow_redirects=True)
    assert b"on loan" in r.data
    r = client.post("/issues/1/return", follow_redirects=True)
    assert b"Book returned" in r.data
    r = client.post("/books/1/delete", follow_redirects=True)
    assert b"Book deleted" in r.data


def test_search(client):
    login(client)
    add_book(client)
    add_student(client)
    assert b"Robert Martin" in client.get("/search?q=clean&scope=books").data
    assert b"Asha" in client.get("/search?q=R1&scope=students").data
    assert b"match" in client.get("/search?q=zzzz").data
