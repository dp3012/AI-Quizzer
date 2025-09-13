from django.contrib import admin
from .models import UserProfile, Quiz, Question, Submission
# Register your models here.

admin.site.register(UserProfile)
admin.site.register(Quiz)
admin.site.register(Question)
admin.site.register(Submission)

