"""课程运营管理系统——CRUD + 容量检查 + WAL 回放。"""
from __future__ import annotations
from typing import Optional
from ..db import Store


def init(store: Store):
    store._init_course_tables(store.conn)


def add_course(store: Store, name: str, teacher: str = "",
               description: str = "", start_date: str = "", end_date: str = "",
               capacity: int = 0, price: float = 0) -> int:
    init(store)
    store.conn.execute(
        "INSERT INTO courses (name, teacher, description, start_date, end_date, capacity, price) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, teacher, description, start_date, end_date, capacity, price))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_courses(store: Store, status: str | None = None) -> list[dict]:
    init(store)
    if status:
        return store.conn.execute(
            "SELECT * FROM courses WHERE status=? ORDER BY start_date DESC", (status,)).fetchall()
    return store.conn.execute(
        "SELECT * FROM courses ORDER BY start_date DESC").fetchall()


def get_course(store: Store, cid: int) -> dict | None:
    init(store)
    return store.conn.execute(
        "SELECT c.*, (SELECT count(*) FROM enrollments WHERE course_id=c.id) as enrolled_count "
        "FROM courses c WHERE c.id=?", (cid,)).fetchone()


def add_lesson(store: Store, course_id: int, title: str, lesson_date: str,
               start_time: str = "", end_time: str = "", location: str = "",
               content: str = "") -> int:
    init(store)
    store.conn.execute(
        "INSERT INTO lessons (course_id, title, lesson_date, start_time, end_time, location, content) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (course_id, title, lesson_date, start_time, end_time, location, content))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_lessons(store: Store, course_id: int) -> list[dict]:
    init(store)
    return store.conn.execute(
        "SELECT * FROM lessons WHERE course_id=? ORDER BY lesson_date ASC, id ASC",
        (course_id,)).fetchall()


def enroll_student(store: Store, course_id: int, student_name: str,
                   student_phone: str = "") -> int:
    init(store)
    course = get_course(store, course_id)
    if not course:
        raise ValueError("课程不存在")
    if course["capacity"] > 0 and (course["enrolled_count"] or 0) >= course["capacity"]:
        raise ValueError(f"课程已满（{course['capacity']}人）")
    store.conn.execute(
        "INSERT INTO enrollments (course_id, student_name, student_phone) VALUES (?, ?, ?)",
        (course_id, student_name, student_phone))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_enrollments(store: Store, course_id: int | None = None) -> list[dict]:
    init(store)
    if course_id:
        return store.conn.execute(
            "SELECT e.*, c.name as course_name FROM enrollments e "
            "JOIN courses c ON e.course_id=c.id "
            "WHERE e.course_id=? ORDER BY e.id DESC", (course_id,)).fetchall()
    return store.conn.execute(
        "SELECT e.*, c.name as course_name FROM enrollments e "
        "JOIN courses c ON e.course_id=c.id ORDER BY e.id DESC").fetchall()


def record_grade(store: Store, enrollment_id: int, score: float,
                 lesson_id: int = 0, comment: str = "") -> int:
    init(store)
    lid = lesson_id if lesson_id else None
    store.conn.execute(
        "INSERT INTO grades (enrollment_id, lesson_id, score, comment) VALUES (?, ?, ?, ?)",
        (enrollment_id, lid, score, comment))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_grades(store: Store, enrollment_id: int) -> list[dict]:
    init(store)
    return store.conn.execute(
        "SELECT g.*, l.title as lesson_title FROM grades g "
        "LEFT JOIN lessons l ON g.lesson_id=l.id "
        "WHERE g.enrollment_id=? ORDER BY g.id ASC", (enrollment_id,)).fetchall()


# ── WAL 回放 ──
def apply_course(store: Store, op: str, row_id: int, payload: dict):
    if op == "INSERT":
        add_course(store, **payload)
    elif op == "DELETE":
        store.conn.execute("DELETE FROM courses WHERE id=?", (row_id,))


def apply_lesson(store: Store, op: str, row_id: int, payload: dict):
    if op == "INSERT":
        add_lesson(store, **payload)


def apply_enrollment(store: Store, op: str, row_id: int, payload: dict):
    if op == "INSERT":
        enroll_student(store, **payload)


def apply_grade(store: Store, op: str, row_id: int, payload: dict):
    if op == "INSERT":
        record_grade(store, **payload)
