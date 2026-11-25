from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.http import HttpResponseRedirect

from .models import Choice, Course, Enrollment, Question, Submission
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.views import generic
from django.contrib.auth import login, logout, authenticate
import logging
# Get an instance of a logger
logger = logging.getLogger(__name__)
# Create your views here.


def registration_request(request):
    context = {}
    if request.method == 'GET':
        return render(request, 'onlinecourse/user_registration_bootstrap.html', context)
    elif request.method == 'POST':
        # Check if user exists
        username = request.POST['username']
        password = request.POST['psw']
        first_name = request.POST['firstname']
        last_name = request.POST['lastname']
        user_exist = False
        try:
            User.objects.get(username=username)
            user_exist = True
        except:
            logger.error("New user")
        if not user_exist:
            user = User.objects.create_user(username=username, first_name=first_name, last_name=last_name,
                                            password=password)
            login(request, user)
            return redirect("onlinecourse:index")
        else:
            context['message'] = "User already exists."
            return render(request, 'onlinecourse/user_registration_bootstrap.html', context)


def login_request(request):
    context = {}
    if request.method == "POST":
        username = request.POST['username']
        password = request.POST['psw']
        user = authenticate(username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('onlinecourse:index')
        else:
            context['message'] = "Invalid username or password."
            return render(request, 'onlinecourse/user_login_bootstrap.html', context)
    else:
        return render(request, 'onlinecourse/user_login_bootstrap.html', context)


def logout_request(request):
    logout(request)
    return redirect('onlinecourse:index')


def check_if_enrolled(user, course):
    is_enrolled = False
    if user.id is not None:
        # Check if user enrolled
        num_results = Enrollment.objects.filter(user=user, course=course).count()
        if num_results > 0:
            is_enrolled = True
    return is_enrolled


# CourseListView
class CourseListView(generic.ListView):
    template_name = 'onlinecourse/course_list_bootstrap.html'
    context_object_name = 'course_list'

    def get_queryset(self):
        user = self.request.user
        courses = Course.objects.order_by('-total_enrollment')[:10]
        for course in courses:
            if user.is_authenticated:
                course.is_enrolled = check_if_enrolled(user, course)
        return courses


class CourseDetailView(generic.DetailView):
    model = Course
    template_name = 'onlinecourse/course_details_bootstrap.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['lessons'] = self.object.lesson_set.order_by('order', 'pk')
        context['questions'] = course_questions(self.object)
        context['is_enrolled'] = check_if_enrolled(self.request.user, self.object)
        return context


def enroll(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    user = request.user

    is_enrolled = check_if_enrolled(user, course)
    if not is_enrolled and user.is_authenticated:
        # Create an enrollment
        Enrollment.objects.create(user=user, course=course, mode='honor')
        course.total_enrollment += 1
        course.save()

    return HttpResponseRedirect(reverse(viewname='onlinecourse:course_details', args=(course.id,)))


PASS_PERCENT = 70


def course_questions(course):
    return Question.objects.filter(lesson__course=course).order_by(
        "lesson__order", "lesson_id", "pk"
    ).prefetch_related("choice_set")


@login_required(login_url="onlinecourse:login")
@require_POST
def submit(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    enrollment = Enrollment.objects.filter(user=request.user, course=course).order_by("pk").first()
    if enrollment is None or not course_questions(course).exists():
        return HttpResponseBadRequest("Enroll in a course with an exam before submitting.")

    try:
        selected_ids = {int(value) for value in request.POST.getlist("choice")}
    except ValueError:
        return HttpResponseBadRequest("Invalid choice.")

    choices = Choice.objects.filter(pk__in=selected_ids, question__lesson__course=course)
    if choices.count() != len(selected_ids):
        return HttpResponseBadRequest("A selected choice does not belong to this exam.")

    with transaction.atomic():
        submission = Submission.objects.create(enrollment=enrollment)
        submission.choices.set(choices)
    return redirect("onlinecourse:show_exam_result", course_id=course.pk, submission_id=submission.pk)


@login_required(login_url="onlinecourse:login")
def show_exam_result(request, course_id, submission_id):
    course = get_object_or_404(Course, pk=course_id)
    submission = get_object_or_404(
        Submission, pk=submission_id, enrollment__course=course, enrollment__user=request.user
    )
    selected_ids = set(submission.choices.values_list("pk", flat=True))
    results = []
    earned = possible = 0
    for question in course_questions(course):
        choices = list(question.choice_set.all())
        chosen = [choice for choice in choices if choice.pk in selected_ids]
        correct = [choice for choice in choices if choice.is_correct]
        is_correct = question.is_get_score(choice.pk for choice in chosen)
        points = question.grade if is_correct else 0
        earned += points
        possible += question.grade
        results.append({
            "question": question, "chosen": chosen, "correct": correct,
            "is_correct": is_correct, "points": points,
        })

    return render(request, "onlinecourse/exam_result_bootstrap.html", {
        "course": course, "results": results, "earned": earned, "possible": possible,
        "score": round(100 * earned / possible) if possible else 0,
        "passed": bool(possible and 100 * earned >= PASS_PERCENT * possible),
    })
