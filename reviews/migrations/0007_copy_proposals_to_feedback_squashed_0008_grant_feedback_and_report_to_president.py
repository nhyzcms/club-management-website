"""Squash reviews 0007–0008.

Old installs already copied Proposal → Feedback and granted perms; ``replaces``
marks this applied. New installs skip the copy (there is no Proposal table)
and only seed reviews.view_feedback / handle_report onto 社长.
"""
from django.db import migrations


def grant_and_drop(apps, schema_editor):
    from django.apps import apps as real_apps
    from django.contrib.auth.management import create_permissions
    from django.contrib.contenttypes.management import create_contenttypes

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    for app_config in real_apps.get_app_configs():
        create_contenttypes(app_config, apps=apps, verbosity=0)
        create_permissions(app_config, apps=apps, verbosity=0)

    group, _ = Group.objects.get_or_create(name="社长")
    for app_label, codename in (("reviews", "view_feedback"), ("reviews", "handle_report")):
        perm = Permission.objects.get(content_type__app_label=app_label, codename=codename)
        group.permissions.add(perm)
    stale = Permission.objects.filter(
        content_type__app_label="proposals",
        codename__in=["approve_proposal", "view_feedback", "change_proposal"],
    )
    if stale.exists():
        group.permissions.remove(*stale)


class Migration(migrations.Migration):

    replaces = [
        ("reviews", "0007_copy_proposals_to_feedback"),
        ("reviews", "0008_grant_feedback_and_report_to_president"),
    ]

    dependencies = [
        ("reviews", "0006_feedback_report_models"),
        ("accounts", "0002_seed_default_groups"),
    ]

    operations = [
        migrations.RunPython(grant_and_drop, migrations.RunPython.noop),
    ]
