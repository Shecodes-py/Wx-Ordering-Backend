from django.core.management.base import BaseCommand

from payments.services import seed_squad_va_pool


class Command(BaseCommand):
    help = (
        "Pull fresh accounts into Squad's dynamic virtual-account pool. "
        "Run once after Squad grants dynamic-VA access, and again later if "
        "checkout starts failing with pool-exhausted errors."
    )

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=5, help='Number of accounts to add to the pool.')

    def handle(self, *args, **options):
        count = options['count']
        accounts = seed_squad_va_pool(count=count)
        self.stdout.write(self.style.SUCCESS(f"Added {len(accounts)} account(s) to the Squad VA pool."))
        for acc in accounts:
            self.stdout.write(f"  {acc.get('virtual_account_number') or acc}")
