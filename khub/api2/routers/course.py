"""课程路由（courses/lessons/enrollments/grades）。"""

from fastapi import APIRouter, Depends
from ..deps import get_store
from ...db import Store


def _safe_int(vals, default=0):
    try:
        return int(vals[0]) if vals else default
    except Exception:
        return default


router = APIRouter(tags=["course"])


@router.post("/api/courses")
async def create_course(body: dict, store: Store = Depends(get_store)):
    from ...course.store import add_course
    cid = add_course(store, name=body.get("name", ""), description=body.get("description", ""),
                     teacher=body.get("instructor", ""), price=body.get("price", 0))
    return {"course_id": cid}


@router.get("/api/courses")
async def list_courses(store: Store = Depends(get_store)):
    from ...course.store import list_courses as _list_courses
    return {"courses": _list_courses(store)}


@router.get("/api/courses/{course_id}")
async def get_course(course_id: int, store: Store = Depends(get_store)):
    from ...course.store import get_course as _get_course
    course = _get_course(store, course_id)
    if not course:
        from fastapi import HTTPException
        raise HTTPException(404, "course not found")
    return {"course": course}


@router.post("/api/courses/{course_id}/lessons")
async def add_lesson(course_id: int, body: dict, store: Store = Depends(get_store)):
    from ...course.store import add_lesson as _add_lesson
    lid = _add_lesson(store, course_id, title=body.get("title", ""),
                      content=body.get("content", ""),
                      lesson_date=body.get("lesson_date", ""))
    return {"lesson_id": lid}


@router.get("/api/courses/{course_id}/lessons")
async def list_lessons(course_id: int, store: Store = Depends(get_store)):
    from ...course.store import list_lessons as _list_lessons
    return {"lessons": _list_lessons(store, course_id)}


@router.post("/api/courses/{course_id}/enroll")
async def enroll_student(course_id: int, body: dict, store: Store = Depends(get_store)):
    from ...course.store import enroll_student as _enroll_student
    try:
        eid = _enroll_student(store, course_id, student_name=body.get("student_name", ""),
                              student_phone=body.get("student_phone", ""))
        return {"enrollment_id": eid}
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(400, str(e))


@router.get("/api/courses/{course_id}/enrollments")
async def list_enrollments(course_id: int, store: Store = Depends(get_store)):
    from ...course.store import list_enrollments as _list_enrollments
    return {"enrollments": _list_enrollments(store, course_id)}


@router.post("/api/grades")
async def record_grade(body: dict, store: Store = Depends(get_store)):
    from ...course.store import record_grade as _record_grade
    gid = _record_grade(store, int(body.get("enrollment_id", 0)),
                        float(body.get("score", 0)),
                        lesson_id=int(body.get("lesson_id", 0)),
                        comment=body.get("comment", ""))
    return {"grade_id": gid}


@router.get("/api/enrollments/{enrollment_id}/grades")
async def list_grades(enrollment_id: int, store: Store = Depends(get_store)):
    from ...course.store import list_grades as _list_grades
    return {"grades": _list_grades(store, enrollment_id)}
