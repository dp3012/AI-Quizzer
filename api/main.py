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
import json
import datetime
import re
from django.utils import timezone
from django.contrib.auth.models import User
from django.db.models import Q, Max
from typing import List, Optional
from . import ai_service
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

class LeaderboardEntry(BaseModel):
    rank: int
    username: str
    top_score: int
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
hint_cache = {}

@app.post("/quiz/generate", response_model=QuizOut)
def generate_quiz(payload: GenerateQuizIn, user: User = Depends(get_current_user)):
    """
    Generates a new quiz, eventually using AI and adaptive difficulty.
    """
    
    user_profile = user.profile
    performance = user_profile.performance_metrics.get(payload.subject, {"correct": 0, "total": 0})
    success_rate = performance['correct'] / performance['total'] if performance['total'] > 0 else 0.5

    quiz = Quiz.objects.create(
        title=f'{payload.subject} Quiz for Grade {payload.grade}',
        grade=payload.grade,
        subject=payload.subject,
        max_score=payload.max_score, 
    )

    prompt = (
        f'You are a quiz generation AI. Generate {payload.total_questions} multiple-choice questions for a quiz on the subject of "{payload.subject}" for a grade {payload.grade} student. '
        f'The student has a historical success rate of {success_rate:.0%} in this subject, so adjust the difficulty mix accordingly (e.g., more easy questions for low success rate). '
        'Provide your response as a single valid JSON object. Do not include any text, code block formatting, or explanations before or after the JSON object. '
        'The JSON object must contain a single key "questions" which is a list of question objects. '
        'Each question object must have exactly these keys: "text" (string), "options" (a list of 4 strings), "correct_answer" (a string that is one of the options), and "difficulty" (a string: "easy", "medium", or "hard").'
    )

    try:
        ai_response = ai_service.generate_json_response(prompt)
        questions_data = ai_response.get("questions", [])

        questions_to_create = []
        for q_data in questions_data:
            # Basic validation
            if not all(key in q_data for key in ["text", "options", "correct_answer", "difficulty"]):
                continue # Skip malformed question data

            q = Question(
                quiz=quiz,
                text=q_data["text"],
                options={"choices": q_data["options"]},
                correct_answer=q_data["correct_answer"],
                difficulty=q_data["difficulty"]
            )
            questions_to_create.append(q)

        if not questions_to_create:
            raise ValueError("AI returned no valid questions.")
        
        Question.objects.bulk_create(questions_to_create)

    except (HTTPException, ValueError) as e:
        quiz.delete()
        print(f"AI generation failed, falling back. Error: {e}")
        raise HTTPException(status_code=500, detail="AI service failed to generate the quiz.")
    
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
    
    # --- Scoring Logic ---
    if total_questions == 0:
        points_per_question = 0
    else:
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
            calculated_score += points_per_question 
        
        detailed_results.append({
            "question_id": question.id,
            "is_correct": is_correct,
            "user_answer": resp.userResponse,
            "correct_answer": question.correct_answer
        })
        user_answers[str(question.id)] = resp.userResponse
    
    submission = Submission.objects.create(
        quiz=quiz,
        user=user,
        answers=user_answers,
        results=detailed_results,
        score=round(calculated_score), 
        max_score=quiz.max_score, 
    )

    wrong_questions = []
    for result in detailed_results:
        if not result["is_correct"]:
            # find full question text from the questions map
            question_text = questions.get(result['question_id']).text
            wrong_questions.append(question_text)

    ai_suggestions = ["No specific suggestions at this time."]
    if wrong_questions:
        missed = "\n- ".join(wrong_questions)
        prompt = (
            f"You are an encouraging tutor. A student missed the following questions in a '{quiz.subject}' quiz. "
            f"Based on these mistakes, provide exactly two distinct, actionable tips for improvement. "
            f"Keep the tips concise and encouraging. Start each tip with a bullet point. "
            f"Do not explain the answers, focus on the underlying concepts.\n"
            f"Missed Questions:\n- {missed}"
        )
        suggestions_text = ai_service.generate_text_response(prompt)
        ai_suggestions = [
            t.strip(" *\n") for t in re.split(r"\n\s*\*\s+", suggestions_text) if t.strip()
        ]

    # # --- AI Feature: Result Suggestions ---
    # # TODO: AI Integration
    # # 1. Analyze the `detailed_results` list for incorrect answers.
    # # 2. Get the text of the questions the user got wrong.
    # # 3. Send these topics/questions to your AI model and ask for 2 improvement tips.
    # ai_suggestions = [
    #     "Suggestion 1: Review the topic of photosynthesis.",
    #     "Suggestion 2: Practice more problems involving fractions."
    # ] # Mock response
    # # --- End AI Integration ---
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
    # the submission itself will be marked as a retry upon next submission
    # for now, we just return the quiz data again for the user to take
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
    # Caching logic
    if payload.questionId in hint_cache:
        return {"questionId": payload.questionId, "hint": hint_cache[payload.questionId]}
    
    try:
        question = Question.objects.get(id=payload.questionId)
    except Question.DoesNotExist:
        raise HTTPException(status_code=404, detail="Question not found")
    
    prompt = (
        f"You are a helpful quiz assistant. Provide a short, one-sentence hint for the following multiple-choice question. "
        f"The hint must guide the user toward the correct thinking process without revealing the answer. "
        f"Question: \"{question.text}\" Options: {question.options.get('choices', [])}"
    )

    ai_hint = ai_service.generate_text_response(prompt)

    # Cache the hint
    hint_cache[payload.questionId] = ai_hint.strip()

    return {"questionId": question.id, "hint": ai_hint.strip()}

@app.post("/leaderboard", response_model=List[LeaderboardEntry])
def get_leaderboard(
    subject: Optional[str] = Query(None),
    grade: Optional[int] = Query(None)
):
    """
    Retrieves the top 10 user scores for a given subject and/or grade.
    If no filters are provided, it returns the overall top 10 scores.
    """
    submissions = Submission.objects.all()

    if subject:
        submissions = submissions.filter(quiz__subject__iexact=subject)
    if grade:
        submissions = submissions.filter(quiz__grade=grade)

    leaderboard_data = submissions.values('user__username').annotate(top_score=Max('score')).order_by('-top_score')[:10]

    response = [
        LeaderboardEntry(rank=i + 1, username=entry['user__username'], top_score=entry['top_score'])
        for i, entry in enumerate(leaderboard_data)
    ]

    return response