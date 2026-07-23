import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class CalendarConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.calendar"
    verbose_name = "Content Calendar"

    def ready(self):
        from django.db.models.signals import post_migrate

        post_migrate.connect(self._register_recurrence_task, sender=self)

    @staticmethod
    def _register_recurrence_task(sender, **kwargs):
        """Register the daily recurring-posts generator after migrations.

        This is the durable publish cadence: ``generate_recurring_posts`` runs
        daily under ``process_tasks``, materialising scheduled occurrences from
        active RecurrenceRules for the publish engine to publish when due.
        """
        try:
            from background_task.models import Task

            from apps.calendar.tasks import generate_recurring_posts

            if not Task.objects.filter(verbose_name="generate_recurring_posts").exists():
                generate_recurring_posts(
                    repeat=86400,
                    verbose_name="generate_recurring_posts",
                )
                logger.info("Registered recurring-posts task (daily)")
        except Exception:
            logger.debug("Skipping recurrence task registration (database not ready)")
