"""Django admin 任务批量归档。"""
from django.contrib import admin
from django.test import RequestFactory, TestCase

from django.contrib.auth.models import User

from .admin import TaskAdmin
from .factories import make_president
from .models import Task


class TaskAdminArchiveTest(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(username="creator", password="x")
        self.manager = make_president(User.objects.create_user(username="pres", password="x"))
        self.pending = Task.objects.create(
            title="待处理", creator=self.creator, status="pending",
        )
        self.done = Task.objects.create(
            title="已完成", creator=self.creator, status="completed",
        )
        self.factory = RequestFactory()
        self.ma = TaskAdmin(Task, admin.site)
        self.ma.message_user = lambda *a, **k: None

    def _req(self, user):
        req = self.factory.post("/")
        req.user = user
        return req

    def test_cancels_open_and_skips_completed(self):
        qs = Task.objects.filter(pk__in=[self.pending.pk, self.done.pk])
        self.ma.archive_selected(self._req(self.manager), qs)
        self.pending.refresh_from_db()
        self.done.refresh_from_db()
        self.assertEqual(self.pending.status, "cancelled")
        self.assertEqual(self.done.status, "completed")
