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

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import jwt
import datetime
from django.utils import timezone
from django.contrib.auth.models import User
from django.db.models import Q
from typing import List, Optional
from quiz.models import UserProfile, Quiz, Question, Submission

# secret + algorithm from env (or fallback to Django SECRET_KEY)
SECRET_KEY = os.getenv('SECRET_KEY') or 'dev-secret-change-me'
ALGORITHM = 'HS256'
ACCESS_EXP_HOURS = 8

app = FastAPI(title="AI Quizzer - API")
security = HTTPBearer()

# ==== Pydantic Models ====
# -- Input Models --
class LoginIn(BaseModel):
    username: str
    password: str

class GenerateQuizIn(BaseModel):
    grade: int
    subject: str
    total_questions: int = Field(1, gt=0)
    max_score: int = Field(1, gt=0)

class QuizResponseItem(BaseModel):
    questionId: int
    userResponse: str

class QuizSubmitRequest(BaseModel):
    quizId: int
    responses: List[QuizResponseItem]

class HintRequest(BaseModel):
    questionId: int

class QuizResponseItem(BaseModel):
    questionId: int
    userResponse: str

# -- Output Models --
class QuestionOut(BaseModel):
    id: int
    text: str
    options: dict
    difficulty: str

class QuizOut(BaseModel):
    quiz_id: int
    title: str
    subject: str
    grade: int
    questions: List[QuestionOut]

class SubmissionResultOut(BaseModel):
    question_id: int
    is_correct: bool
    user_answer: str
    correct_answer: str

class SubmissionOut(BaseModel):
    id: int
    quiz_title: str
    score: int
    max_score: int
    submitted_at: datetime.datetime
    is_retry: bool

# === Authentication & User Handling ===
def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)) -> User:
    """
    Decodes JWT token and returns the corresponding Django User object.
    Creates the user if they don't exist (useful for this mock setup).
    """
    token = creds.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        
        # Get or create the user in the database
        user, created = User.objects.get_or_create(username=username)
        if created:
            UserProfile.objects.create(user=user) # Create their profile too
        return user

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.post("/auth/login")
def login(payload: LoginIn):
    """
    Mock authentication: accept ANY username/password and return a signed JWT.
    """
    now = timezone.now()
    exp = now + datetime.timedelta(hours=ACCESS_EXP_HOURS)
    claims = {
        "sub": payload.username, 
        "iat": now, 
        "exp": exp
    }
    token = jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}

@app.get("/protected/example")
def protected_example(username: str = Depends(get_current_user)):
    return {"msg": f"Hello {username}. Token valid."}

# === API Endpoints ===
@app.post("/quiz/generate", response_model=QuizOut)
def generate_quiz(payload: GenerateQuizIn, user: User = Depends(get_current_user)):
    """
    Generates a new quiz, eventually using AI and adaptive difficulty.
    """
    # --- AI Feature: Adaptive Question Difficulty ---
    # TODO: AI Integration
    # 1. Fetch user's performance history from their UserProfile.
    #    user_profile = user.profile
    #    performance = user_profile.performance_metrics.get(payload.subject, {"correct": 0, "total": 0})
    #    success_rate = performance['correct'] / performance['total'] if performance['total'] > 0 else 0.5
    # 2. Based on success_rate, determine the mix of easy/medium/hard questions.
    #    e.g., if success_rate < 0.4, generate 5 easy, 3 medium, 2 hard.
    # 3. Call your AI model to generate questions with the specified difficulty.
    
    # Mock Implementation
    quiz = Quiz.objects.create(
        title=f'{payload.subject} Quiz for Grade {payload.grade}',
        grade=payload.grade,
        subject=payload.subject,
        max_score=payload.max_score, # <-- Save the max_score
    )

    questions_to_create = []
    difficulties = ['easy'] * 5 + ['medium'] * 3 + ['hard'] * 2 # Mock distribution
    for i in range(payload.total_questions):
        q = Question(
            quiz=quiz,
            text=f"Mock '{difficulties[i]}' question {i+1} for {payload.subject}?",
            options={"choices": ["A", "B", "C", "D"]},
            correct_answer="A",
            difficulty=difficulties[i]
        )
        questions_to_create.append(q)
    Question.objects.bulk_create(questions_to_create)
    # --- End Mock Implementation ---
    
    return QuizOut(
        quiz_id=quiz.id,
        title=quiz.title,
        subject=quiz.subject,
        grade=quiz.grade,
        questions=[QuestionOut(**q.__dict__) for q in quiz.questions.all()]
    )

@app.post("/quiz/submit")
def submit_quiz(payload: QuizSubmitRequest, user: User = Depends(get_current_user)):
    """
    Submits quiz answers, evaluates them, and provides AI-powered suggestions.
    """
    try:
        quiz = Quiz.objects.prefetch_related('questions').get(id=payload.quizId)
    except Quiz.DoesNotExist:
        raise HTTPException(status_code=404, detail="Quiz not found")

    questions = {q.id: q for q in quiz.questions.all()}
    total_questions = len(questions)
    
    # --- New Scoring Logic ---
    if total_questions == 0:
        points_per_question = 0
    else:
        # Calculate the value of each question
        points_per_question = quiz.max_score / total_questions
    
    correct_count = 0
    calculated_score = 0
    detailed_results = []
    user_answers = {}

    for resp in payload.responses:
        question = questions.get(resp.questionId)
        if not question:
            continue

        is_correct = resp.userResponse.strip().lower() == question.correct_answer.strip().lower()
        if is_correct:
            correct_count += 1
            calculated_score += points_per_question # <-- Add points, not just 1
        
        detailed_results.append({
            "question_id": question.id,
            "is_correct": is_correct,
            "user_answer": resp.userResponse,
            "correct_answer": question.correct_answer
        })
        user_answers[str(question.id)] = resp.userResponse
    
    # Create the submission record with the new score
    submission = Submission.objects.create(
        quiz=quiz,
        user=user,
        answers=user_answers,
        results=detailed_results,
        score=round(calculated_score), # <-- Use the calculated score (rounded)
        max_score=quiz.max_score, # <-- Store the quiz's max_score
    )
    # --- AI Feature: Result Suggestions ---
    # TODO: AI Integration
    # 1. Analyze the `detailed_results` list for incorrect answers.
    # 2. Get the text of the questions the user got wrong.
    # 3. Send these topics/questions to your AI model and ask for 2 improvement tips.
    ai_suggestions = [
        "Suggestion 1: Review the topic of photosynthesis.",
        "Suggestion 2: Practice more problems involving fractions."
    ] # Mock response
    # --- End AI Integration ---
    return {
        "submissionId": submission.id,
        "score": submission.score,
        "maxScore": submission.max_score,
        "correctQuestions": correct_count,
        "totalQuestions": total_questions,
        "submittedAt": submission.submitted_at,
        "suggestions": ai_suggestions
    }

@app.get("/quiz/history", response_model=List[SubmissionOut])
def get_quiz_history(
    user: User = Depends(get_current_user),
    subject: Optional[str] = Query(None),
    grade: Optional[int] = Query(None),
    from_date: Optional[datetime.date] = Query(None, alias="from"),
    to_date: Optional[datetime.date] = Query(None, alias="to")
):
    """
    Retrieves quiz history for the current user with powerful filtering.
    """
    filters = Q(user=user)
    if subject:
        filters &= Q(quiz__subject__icontains=subject)
    if grade:
        filters &= Q(quiz__grade=grade)
    if from_date:
        filters &= Q(submitted_at__date__gte=from_date)
    if to_date:
        filters &= Q(submitted_at__date__lte=to_date)
    
    submissions = Submission.objects.filter(filters).select_related('quiz').order_by('-submitted_at')
    
    return [
        SubmissionOut(
            id=s.id,
            quiz_title=s.quiz.title,
            score=s.score,
            max_score=s.max_score,
            submitted_at=s.submitted_at,
            is_retry=s.is_retry
        ) for s in submissions
    ]

@app.post("/quiz/retry/{submission_id}", response_model=QuizOut)
def retry_quiz(submission_id: int, user: User = Depends(get_current_user)):
    """
    Allows a user to retry a previously taken quiz.
    This creates a new submission attempt for an existing quiz definition.
    """
    try:
        # Ensure the user is retrying their own submission
        submission = Submission.objects.select_related('quiz').get(id=submission_id, user=user)
    except Submission.DoesNotExist:
        raise HTTPException(status_code=404, detail="Submission not found or you do not have permission to retry it.")

    quiz = submission.quiz
    # The submission itself will be marked as a retry upon next submission
    # For now, we just return the quiz data again for the user to take.
    return QuizOut(
        quiz_id=quiz.id,
        title=quiz.title,
        subject=quiz.subject,
        grade=quiz.grade,
        questions=[QuestionOut(**q.__dict__) for q in quiz.questions.all()]
    )

@app.post("/quiz/hint")
def get_hint(payload: HintRequest, user: User = Depends(get_current_user)):
    """
    Provides an AI-generated hint for a specific question.
    """
    try:
        question = Question.objects.get(id=payload.questionId)
    except Question.DoesNotExist:
        raise HTTPException(status_code=404, detail="Question not found")

    # --- AI Feature: Hint Generation ---
    # TODO: AI Integration
    # 1. Pass the question.text and question.options to your AI model.
    # 2. Ask it to generate a helpful, non-direct hint.
    ai_hint = f"Mock Hint: Think about what happens when you add the two numbers in the question: '{question.text}'" # Mock response
    # --- End AI Integration ---

    return {"questionId": question.id, "hint": ai_hint}