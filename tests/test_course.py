"""课程运营管理系统测试。"""
import pytest
from khub.db import Store
from khub.course.store import (
    add_course, list_courses, get_course,
    add_lesson, list_lessons,
    enroll_student, list_enrollments,
    record_grade, list_grades,
)


def test_add_course():
    store = Store(":memory:")
    cid = add_course(store, "中医基础", teacher="张教授", start_date="2026-08-01")
    assert cid > 0
    course = get_course(store, cid)
    assert course["name"] == "中医基础"
    assert course["teacher"] == "张教授"


def test_list_courses():
    store = Store(":memory:")
    add_course(store, "课程A"); add_course(store, "课程B")
    assert len(list_courses(store)) == 2


def test_list_courses_by_status():
    store = Store(":memory:")
    add_course(store, "课程A")  # default active
    courses = list_courses(store, status="active")
    assert len(courses) >= 1
    assert list_courses(store, status="finished") == []


def test_add_lesson():
    store = Store(":memory:")
    cid = add_course(store, "中医基础")
    lid = add_lesson(store, cid, "阴阳学说", "2026-08-01", start_time="09:00")
    assert lid > 0
    lessons = list_lessons(store, cid)
    assert len(lessons) == 1
    assert lessons[0]["title"] == "阴阳学说"


def test_enroll_student():
    store = Store(":memory:")
    cid = add_course(store, "中医基础", capacity=10)
    eid = enroll_student(store, cid, "张三", "13800138000")
    assert eid > 0
    enrollments = list_enrollments(store, cid)
    assert len(enrollments) == 1
    assert enrollments[0]["student_name"] == "张三"


def test_enroll_capacity_full():
    store = Store(":memory:")
    cid = add_course(store, "小班课", capacity=1)
    enroll_student(store, cid, "张三")
    with pytest.raises(ValueError, match="已满"):
        enroll_student(store, cid, "李四")


def test_enroll_course_not_found():
    store = Store(":memory:")
    with pytest.raises(ValueError, match="不存在"):
        enroll_student(store, 999, "张三")


def test_record_grade():
    store = Store(":memory:")
    cid = add_course(store, "中医基础")
    eid = enroll_student(store, cid, "张三")
    gid = record_grade(store, eid, 95.5, comment="优秀")
    assert gid > 0
    grades = list_grades(store, eid)
    assert len(grades) == 1
    assert grades[0]["score"] == 95.5


def test_course_with_enrolled_count():
    store = Store(":memory:")
    cid = add_course(store, "中医基础", capacity=10)
    enroll_student(store, cid, "张三")
    course = get_course(store, cid)
    assert course["enrolled_count"] == 1
