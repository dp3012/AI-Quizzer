from django.db import models
from django.contrib.auth.models import User
# Create your models here.
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    def __str__(self):
        return self.user.username
    
class Quiz(models.Model):
    title = models.CharField(max_length=255)
    subject = models.CharField(max_length=100, null=True, blank=True)
    grade = models.IntegerField(default=1, null=True, blank=True)
    difficulty = models.CharField(max_length=50, default="medium")
    max_score = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return self.title

class Question(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField()
    options = models.JSONField(default=list)   # list of options ["A", "B", "C", "D"]
    correct_answer = models.CharField(max_length=250)
    def __str__(self):
        return f"Question for {self.quiz.title}"
    
class Submission(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    answers = models.JSONField(default=dict)  # {"q1": "A", "q2": "C"}
    score = models.IntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"Submission by {self.user.username} for {self.quiz.title}"