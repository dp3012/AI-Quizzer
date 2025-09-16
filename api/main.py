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
from fastapi.responses import HTMLResponse
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

class SubmissionOut(BaseModel):
    id: int
    quiz_title: str
    score: int
    max_score: int
    submitted_at: datetime.datetime
    is_retry: bool

class QuestionReview(BaseModel):
    question_text: str
    your_answer: str
    correct_answer: str
    is_correct: bool

class SubmissionReviewOut(BaseModel):
    submission_id: int
    quiz_title: str
    score: int
    max_score: int
    submitted_at: datetime.datetime
    questions: List[QuestionReview]

class LeaderboardEntry(BaseModel):
    rank: int
    username: str
    top_score: int

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AI Quizzer API</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Roboto+Mono:wght@400;700&display=swap');
            
            body {
                font-family: 'Roboto Mono', monospace;
                background-color: #121212;
                color: #e0e0e0;
                margin: 0;
                padding: 40px;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                box-sizing: border-box;
            }
            .container {
                max-width: 800px;
                width: 100%;
                background-color: #1e1e1e;
                border: 1px solid #333;
                border-radius: 8px;
                padding: 40px;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
                text-align: center;
            }
            h1 {
                color: #bb86fc;
                font-size: 2.5em;
                margin-bottom: 10px;
            }
            p {
                font-size: 1.1em;
                line-height: 1.6;
            }
            .status {
                display: inline-block;
                background-color: #03dac6;
                color: #121212;
                padding: 8px 15px;
                border-radius: 20px;
                font-weight: bold;
                margin: 20px 0;
            }
            .section {
                text-align: left;
                margin-top: 40px;
                border-top: 1px solid #333;
                padding-top: 20px;
            }
            h2 {
                color: #03dac6;
                font-size: 1.8em;
                border-bottom: 2px solid #bb86fc;
                padding-bottom: 10px;
                margin-bottom: 20px;
            }
            ul {
                list-style: none;
                padding: 0;
            }
            li {
                background-color: #2a2a2a;
                padding: 15px;
                border-radius: 5px;
                margin-bottom: 10px;
                font-size: 1.1em;
            }
            .buttons {
                margin-top: 30px;
                display: flex;
                justify-content: center;
                gap: 20px;
            }
            a.button {
                text-decoration: none;
                color: #121212;
                background-color: #bb86fc;
                padding: 15px 30px;
                border-radius: 5px;
                font-weight: bold;
                transition: transform 0.2s, background-color 0.2s;
            }
            a.button:hover {
                transform: translateY(-3px);
                background-color: #cf9fff;
            }
            a.button-secondary {
                background-color: #03dac6;
            }
            a.button-secondary:hover {
                background-color: #5dfde9;
            }
            .tech-stack {
                margin-top: 40px;
                font-size: 0.9em;
                color: #4DB6AC;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>AI Quizzer APP</h1>
            <p>A smart, adaptive quiz generation and evaluation service.</p>
            <div class="status">App is Online</div>

            <div class="section">
                <h2>Getting Started</h2>
                <p>Interact with the APIs through the documentation or your favorite API client.</p>
                <div class="buttons">
                    <a href="/docs" class="button">API Docs</a>
                    <a href="https://github.com/dp3012/AI-Quizzer" class="button button-secondary" target="_blank">GitHub Repo</a>
                </div>
            </div>

            <div class="section">
                <h2>Key Features</h2>
                <ul>
                    <li><strong>Adaptive Quiz Generation:</strong> Creates quizzes tailored to user performance.</li>
                    <li><strong>AI-Powered Hints:</strong> Provides helpful hints without giving away the answer.</li>
                    <li><strong>Smart Result Suggestions:</strong> Offers personalized improvement tips.</li>
                    <li><strong>Comprehensive History:</strong> Tracks submissions with advanced filtering.</li>
                    <li><strong>Leaderboard:</strong> Ranks top performers by subject and grade.</li>
                </ul>
            </div>

            <div class="tech-stack">
                <p><strong style="color: #bb86fc;">Tech Stack:</strong> FastAPI | Django ORM | PostgreSQL | Docker | Gemini AI | Render</p>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# === Authentication & User Handling ===
def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)) -> User:
    """
    Decodes JWT token and returns the corresponding Django User object if valid.
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
        'Crucially, each option in the "options" list must be a string prefixed with "A. ", "B. ", "C. ", or "D. ". '
        'The "correct_answer" key must contain ONLY the capital letter of the correct option (e.g., "A", "B", "C", or "D").'
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
    detailed_breakdown = []

    for resp in payload.responses:
        question = questions.get(resp.questionId)
        if not question:
            continue

        is_correct = resp.userResponse.strip().upper() == question.correct_answer.strip().upper()
        if is_correct:
            correct_count += 1
            calculated_score += points_per_question 
        
        detailed_breakdown.append({
            "question_text": question.text,
            "is_correct": is_correct,
            "user_answer": resp.userResponse.upper(),
            "correct_answer": question.correct_answer
        })
        # For storing in database
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

    return {
        "submissionId": submission.id,
        "score": submission.score,
        "maxScore": submission.max_score,
        "correctQuestions": correct_count,
        "totalQuestions": total_questions,
        "submittedAt": submission.submitted_at,
        "suggestions": ai_suggestions,
        "detailed_breakdown": detailed_breakdown
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

@app.get("/quiz/history/{submission_id}", response_model=SubmissionReviewOut)
def get_submission_details(submission_id: int, user: User = Depends(get_current_user)):
    """
    Retrieves the detailed results of a specific, single quiz submission
    for the currently authenticated user.
    """
    try:
        submission = Submission.objects.select_related('quiz').get(id=submission_id, user=user)
    except Submission.DoesNotExist:
        raise HTTPException(status_code=404, detail="Submission not found or you do not have permission to view it.")

    question_texts = {q.id: q.text for q in submission.quiz.questions.all()}

    question_reviews = []
    for result_item in submission.results:
        question_id = result_item.get("question_id")
        question_reviews.append(
            QuestionReview(
                question_text=question_texts.get(question_id, "Question text not found."),
                your_answer=result_item.get("user_answer").upper(),
                correct_answer=result_item.get("correct_answer"),
                is_correct=result_item.get("is_correct")
            )
        )

    return SubmissionReviewOut(
        submission_id=submission.id,
        quiz_title=submission.quiz.title,
        score=submission.score,
        max_score=submission.max_score,
        submitted_at=submission.submitted_at,
        questions=question_reviews
    )

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