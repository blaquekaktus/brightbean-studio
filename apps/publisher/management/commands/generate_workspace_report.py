"""Generate a white-label publishing report (HTML) for a workspace.

Usage:
    python manage.py generate_workspace_report <workspace_id> \
        [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--out report.html]

Defaults to the trailing 30 days. Writes to --out, or stdout if omitted.
The HTML is print-ready (browser → PDF); no PDF dependency is required.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.publisher.reports import build_report_data, render_report_html
from apps.workspaces.models import Workspace


def _parse_date(value: str, *, end: bool = False):
    """Parse a YYYY-MM-DD string into a timezone-aware datetime."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CommandError(f"Invalid date '{value}' (expected YYYY-MM-DD).") from exc
    naive = datetime.combine(parsed, time.max if end else time.min)
    return timezone.make_aware(naive, timezone.get_current_timezone())


class Command(BaseCommand):
    help = "Generate a white-label publishing report (HTML) for a workspace."

    def add_arguments(self, parser):
        parser.add_argument("workspace_id", help="Workspace UUID.")
        parser.add_argument("--start", help="Inclusive start date, YYYY-MM-DD.")
        parser.add_argument("--end", help="Exclusive end date, YYYY-MM-DD.")
        parser.add_argument("--out", help="Output HTML path (default: stdout).")

    def handle(self, *args, **options):
        try:
            workspace = Workspace.objects.get(id=options["workspace_id"])
        except (Workspace.DoesNotExist, ValueError) as exc:
            raise CommandError(f"Workspace '{options['workspace_id']}' not found.") from exc

        end = _parse_date(options["end"], end=True) if options.get("end") else timezone.now()
        start = _parse_date(options["start"]) if options.get("start") else end - timedelta(days=30)
        if start >= end:
            raise CommandError("--start must be before --end.")

        report = build_report_data(workspace, start, end)
        html = render_report_html(report, workspace)

        out = options.get("out")
        if out:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(html)
            self.stdout.write(
                self.style.SUCCESS(f"Wrote {out} — {report['total_posts']} posts published for '{workspace.name}'.")
            )
        else:
            self.stdout.write(html)
