"""Issue an ingest token for a workspace and print the raw value once.

The raw token is shown a single time — copy it into the sibling repo's
``BRIGHTBEAN_API_TOKEN`` env var. Only its hash is stored; a lost token cannot
be recovered, only revoked and re-issued.

    python manage.py create_ingest_token --workspace <uuid> --name "ACC theshortcutsai"
"""

from django.core.management.base import BaseCommand, CommandError

from apps.api.models import IngestToken
from apps.workspaces.models import Workspace


class Command(BaseCommand):
    help = "Issue an ingest token for a workspace (prints the raw token once)."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True, help="Workspace UUID.")
        parser.add_argument("--name", required=True, help="Human label for the token.")

    def handle(self, *args, **options):
        try:
            workspace = Workspace.objects.get(id=options["workspace"])
        except (Workspace.DoesNotExist, ValueError) as exc:
            raise CommandError(f"No workspace with id {options['workspace']!r}.") from exc

        token, raw = IngestToken.issue(workspace, options["name"])
        self.stdout.write(self.style.SUCCESS("Ingest token created."))
        self.stdout.write(f"  workspace: {workspace.name} ({workspace.id})")
        self.stdout.write(f"  name:      {token.name}")
        self.stdout.write(f"  token:     {raw}")
        self.stdout.write(
            self.style.WARNING(
                "Store this token now — it is not shown again. Put it in the "
                "sibling's BRIGHTBEAN_API_TOKEN env var (never commit it)."
            )
        )
