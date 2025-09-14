from django.db import models
from django.contrib.auth.models import User
# Create your models here.
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    # This field will store aggregated performance data for the adaptive AI
    # Example: {"math": {"correct": 30, "total": 50}, "science": {"correct": 25, "total": 40}}
    performance_metrics = models.JSONField(default=dict)
    def __str__(self):
        return self.user.username
    
class Quiz(models.Model):
    title = models.CharField(max_length=255)
    subject = models.CharField(max_length=100, null=True, blank=True)
    grade = models.IntegerField(default=1, null=True, blank=True)
    max_score = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return self.title

class Question(models.Model):
    DIFFICULTY_CHOICES = [
        ("easy", "Easy"),
        ("medium", "Medium"),
        ("hard", "Hard"),
    ]
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField()
    options = models.JSONField(default=dict)   
    correct_answer = models.CharField(max_length=255)
    difficulty = models.CharField(max_length=50, choices=DIFFICULTY_CHOICES, default="medium")
    def __str__(self):
        return f"({self.difficulty}) {self.text[:50]}..."
    
class Submission(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="submissions")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="submissions")
    answers = models.JSONField(default=dict)  # {"q1": "A", "q2": "C"}
    results = models.JSONField(default=list)
    score = models.IntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)
    is_retry = models.BooleanField(default=False)
    max_score = models.IntegerField(default=0)
    def __str__(self):
        return f"Submission by {self.user.username} for {self.quiz.title}"