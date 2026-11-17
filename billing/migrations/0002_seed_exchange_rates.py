from decimal import Decimal

from django.db import migrations

# Illustrative static rates for the prototype. Update them in the admin; they are not live market rates.
RATES = {
    "USD": "1",
    "EUR": "1.08",
    "GBP": "1.27",
    "INR": "0.012",
    "JPY": "0.0067",
    "CAD": "0.73",
    "AUD": "0.66",
}


def seed(apps, schema_editor):
    ExchangeRate = apps.get_model("billing", "ExchangeRate")
    for currency, rate in RATES.items():
        ExchangeRate.objects.get_or_create(currency=currency, defaults={"rate_to_usd": Decimal(rate)})


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
