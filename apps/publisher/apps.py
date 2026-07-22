import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class PublisherConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.publisher"
    verbose_name = "Publishing Engine"

    def ready(self):
        from django.db.models.signals import post_migrate

        post_migrate.connect(self._register_publish_task, sender=self)
        post_migrate.connect(self._register_monthly_report_task, sender=self)

    @staticmethod
    def _register_publish_task(sender, **kwargs):
        """Register the recurring publish-cycle task after migrations are applied."""
        try:
            from background_task.models import Task

            from apps.publisher.tasks import run_publish_cycle

            if not Task.objects.filter(verbose_name="run_publish_cycle").exists():
                run_publish_cycle(
                    repeat=15,
                    verbose_name="run_publish_cycle",
                )
                logger.info("Registered recurring publish task (every 15s)")
        except Exception:
            logger.debug("Skipping publish task registration (database not ready)")

    @staticmethod
    def _register_monthly_report_task(sender, **kwargs):
        """Register the recurring monthly-report task after migrations are applied.

        Runs daily; the task itself only acts on the first of the month, giving
        calendar-correct monthly delivery without a dedicated scheduler.
        """
        try:
            from background_task.models import Task

            from apps.publisher.tasks import generate_monthly_reports

            if not Task.objects.filter(verbose_name="generate_monthly_reports").exists():
                generate_monthly_reports(
                    repeat=86400,
                    verbose_name="generate_monthly_reports",
                )
                logger.info("Registered recurring monthly-report task (daily; runs on the 1st)")
        except Exception:
            logger.debug("Skipping monthly-report task registration (database not ready)")
