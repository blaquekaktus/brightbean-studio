"""Background tasks for the publishing engine."""

import logging

from background_task import background

logger = logging.getLogger(__name__)


@background(schedule=0)
def run_publish_cycle():
    """Poll for due posts and publish them.

    Registered as a recurring task (every 15s) so that
    ``python manage.py process_tasks`` handles publishing
    without needing a separate ``run_publisher`` process.
    """
    from apps.publisher.engine import PublishEngine

    engine = PublishEngine()
    published = engine.poll_and_publish()
    if published:
        logger.info("Publish cycle completed - %d post(s) published", published)


@background(schedule=0)
def generate_monthly_reports(force=False):
    """Generate and deliver each workspace's previous-month publishing report.

    Registered as a recurring daily task (see ``apps.publisher.apps``); it
    no-ops except on the first of the month, so ``process_tasks`` delivers
    monthly reports without a separate scheduler.
    """
    from apps.publisher.report_scheduler import run_monthly_reports

    summary = run_monthly_reports(force=force)
    logger.info("Monthly report run: %s", summary)
