"""Join questionnaire admin lives on activities.Questionnaire (kind=join)."""
from django.test import TestCase


class JoinSurveyAdminMovedTest(TestCase):
    def test_old_join_admin_urls_are_gone(self):
        self.assertEqual(self.client.get("/admin/recruitment/joinquestionnaire/").status_code, 302)
        # After login redirect; unauthenticated admin is 302. Hit after superuser in activities tests.
        from django.contrib.auth.models import User
        from django.test import Client

        admin = User.objects.create_superuser("adm", "a@e.com", "x")
        c = Client()
        c.force_login(admin)
        self.assertEqual(c.get("/admin/recruitment/joinquestionnaire/").status_code, 404)
        self.assertEqual(c.get("/admin/recruitment/joinresponse/").status_code, 404)
