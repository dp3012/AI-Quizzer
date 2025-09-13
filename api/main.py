# api/main.py
import os
from pathlib import Path
from dotenv import load_dotenv

# load .env (project root)
BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / '.env')

# Point to Django settings and setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django
django.setup()

from quiz.models import UserProfile, Quiz, Question, Submission
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import jwt
import datetime

# secret + algorithm from env (or fallback to Django SECRET_KEY)
SECRET_KEY = os.getenv('SECRET_KEY') or 'dev-secret-change-me'
ALGORITHM = 'HS256'
ACCESS_EXP_HOURS = 8

app = FastAPI(title="AI Quizzer - API")

security = HTTPBearer()

class LoginIn(BaseModel):
    username: str
    password: str

class GenerateQuizIn(BaseModel):
    grade: int
    subject: str
    total_questions: int
    max_score: int
    difficulty: str

@app.post("/auth/login")
def login(payload: LoginIn):
    """
    Mock authentication: accept ANY username/password and return a signed JWT.
    """
    now = datetime.datetime.utcnow()
    exp = now + datetime.timedelta(hours=ACCESS_EXP_HOURS)
    claims = {
        "sub": payload.username,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer", "expires_at": exp.isoformat()}

def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    token = creds.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return username

@app.get("/protected/example")
def protected_example(username: str = Depends(get_current_user)):
    return {"msg": f"Hello {username}. Token valid."}

@app.post("/quiz/generate")
def generate_quiz(payload: GenerateQuizIn, username: str = Depends(get_current_user)):
    """
    Generates a new quiz with mock questions and saves it in the DB.
    """
    # Create Quiz object
    quiz = Quiz.objects.create(
        title=f'{payload.subject} Quiz - Grade {payload.grade}',
        grade=payload.grade,
        subject=payload.subject,
        max_score=payload.max_score,
        difficulty=payload.difficulty,
    )

    # Generate mock questions
    questions = []
    for i in range(payload.total_questions):
        q_text = f"What is {i+2} + {i+3}?"
        options = [str(i+4), str(i+5), str(i+6), str(i+7)]
        correct_answer = str(i+5)

        q = Question.objects.create(
            quiz=quiz,
            text=q_text,
            options={"choices": options},  # JSONField
            correct_answer=correct_answer,
        )

        questions.append({
            "id": q.id,
            "text": q.text,
            "options": options,
            "correct_answer": correct_answer  # ⚠️ For debugging; in real use hide this
        })

    # Step 3: Return response
    return {
        "quiz_id": quiz.id,
        "title": quiz.title,
        "subject": quiz.subject,
        "grade": quiz.grade,
        "difficulty": quiz.difficulty,
        "questions": questions,
    }