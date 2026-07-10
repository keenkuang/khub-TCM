from khub.db import Store
from khub.exam.models import Question
from khub.exam.store import add_question, get_question, list_questions
from khub.exam.generator import generate
from khub.exam.grader import grade
import pytest
pytestmark = pytest.mark.smoke


def test_crud_question():
    s = Store(":memory:")
    qid = add_question(s, Question(kind="mcq", stem="当归补血汤组成？",
                                   options=["黄芪当归", "人参白术"], answer="黄芪当归",
                                   explanation="黄芪倍当归"))
    assert qid >= 1
    q = get_question(s, qid)
    assert q.stem == "当归补血汤组成？" and q.options == ["黄芪当归", "人参白术"]
    assert len(list_questions(s)) == 1
    assert len(list_questions(s, kind="mcq")) == 1
    assert len(list_questions(s, kind="case")) == 0

def test_generate_returns_well_formed_question():
    s = Store(":memory:")
    q = generate("少阳证")
    assert isinstance(q, Question) and q.stem  # NoOp -> placeholder stem non-empty

def test_grade_exact_match():
    s = Store(":memory:")
    q = Question(kind="mcq", stem="x", answer="A")
    score, fb = grade(q, "A")
    assert score == 1.0
