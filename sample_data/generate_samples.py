"""Generate SIMULATED multi-cloud billing data for the prototype.

Nothing here comes from a real cloud account. Output is deterministic
(seeded) so tests and demos are reproducible.

    python sample_data/generate_samples.py
"""
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent
START = date(2026, 7, 20)
DAYS = 120
rng = random.Random(42)


def amount(base, i, day, growth=0.0, flat=False, spikes=None):
    value = base * (1 + growth) ** i
    if not flat:
        if day.weekday() >= 5:
            value *= 0.85
        value *= 1 + rng.uniform(-0.05, 0.05)
    if spikes and day in spikes:
        value *= spikes[day]
    return round(value, 4)


def days():
    for i in range(DAYS):
        yield i, START + timedelta(days=i)


AWS_PAYER = "111122223333"
AWS_DEV = "444455556666"
AWS_LINES = [
    # usage account, product, resource id, region, unit, base, options
    (AWS_PAYER, "AmazonEC2", "i-0a1b2c3d4e5f60001", "us-east-1", "Hrs", 95, {}),
    (AWS_PAYER, "AmazonEC2", "i-0a1b2c3d4e5f60002", "us-east-1", "Hrs", 70, {"spikes": {date(2026, 11, 10): 3.2}}),
    (AWS_PAYER, "AmazonEC2", "i-0a1b2c3d4e5f60003", "eu-west-1", "Hrs", 48, {}),
    (AWS_DEV, "AmazonEC2", "i-0deadbeef00000009", "us-east-1", "GB-Mo", 6.5, {"flat": True}),
    (AWS_DEV, "AmazonEC2", "vol-0f00ba47000000001", "us-east-1", "GB-Mo", 3.2, {"flat": True}),
    (AWS_PAYER, "AmazonEC2", "", "us-east-1", "GB", 14, {}),
    (AWS_PAYER, "AmazonRDS", "arn:aws:rds:us-east-1:111122223333:db:orders-prod", "us-east-1", "Hrs", 62, {}),
    (AWS_PAYER, "AmazonS3", "acme-prod-assets", "us-east-1", "GB-Mo", 28, {"growth": 0.002}),
    (AWS_PAYER, "AmazonS3", "acme-logs", "us-east-1", "GB-Mo", 12, {}),
    (AWS_PAYER, "AWSLambda", "arn:aws:lambda:us-east-1:111122223333:function:checkout", "us-east-1", "Requests", 9, {}),
    (AWS_PAYER, "AmazonCloudFront", "", "", "GB", 18, {}),
]

AZ_BILLING = "contoso-billing-001"
AZ_PROD = "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-prod/providers"
AZ_DEV = "/subscriptions/22222222-2222-2222-2222-222222222222/resourceGroups/rg-dev/providers"
AZURE_LINES = [
    ("Contoso-Prod", "Virtual Machines", f"{AZ_PROD}/Microsoft.Compute/virtualMachines/vm-web-01", "westeurope", "1 Hour", 60, {}),
    ("Contoso-Prod", "Virtual Machines", f"{AZ_PROD}/Microsoft.Compute/virtualMachines/vm-web-02", "westeurope", "1 Hour", 55, {}),
    ("Contoso-Dev", "Virtual Machines", f"{AZ_DEV}/Microsoft.Compute/virtualMachines/vm-dev-01", "northeurope", "1 Hour", 22, {}),
    ("Contoso-Prod", "Storage", f"{AZ_PROD}/Microsoft.Storage/storageAccounts/contosoprodsa", "westeurope", "1 GB/Month", 16, {}),
    ("Contoso-Prod", "SQL Database", f"{AZ_PROD}/Microsoft.Sql/servers/contoso-sql/databases/orders", "westeurope", "1 Hour", 48, {}),
    ("Contoso-Prod", "Azure App Service", f"{AZ_PROD}/Microsoft.Web/sites/contoso-portal", "westeurope", "1 Hour", 20, {}),
    ("Contoso-Prod", "Bandwidth", "", "westeurope", "1 GB", 8, {"spikes": {date(2026, 11, 5): 3.5}}),
    ("Contoso-Dev", "Storage", f"{AZ_DEV}/Microsoft.Compute/disks/disk-orphan-01", "northeurope", "1 GB/Month", 2.4, {"flat": True}),
    ("Contoso-Dev", "Virtual Network", f"{AZ_DEV}/Microsoft.Network/publicIPAddresses/pip-unused-01", "northeurope", "1 Hour", 0.12, {"flat": True}),
]

GCP_BILLING = "01ABCD-234EFG-567HIJ"
GCP_LINES = [
    ("acme-web-prod", "Compute Engine", "projects/acme-web-prod/zones/us-central1-a/instances/web-1", "us-central1", "seconds", 52, {}),
    ("acme-web-prod", "Compute Engine", "projects/acme-web-prod/zones/us-central1-a/instances/web-2", "us-central1", "seconds", 50, {}),
    ("acme-data", "Compute Engine", "projects/acme-data/zones/europe-west1-b/instances/etl-old", "europe-west1", "byte-seconds", 4.1, {"flat": True}),
    ("acme-data", "Cloud Storage", "projects/_/buckets/acme-data-lake", "europe-west1", "byte-seconds", 15, {}),
    ("acme-data", "BigQuery", "", "europe-west1", "bytes", 35, {"growth": 0.01, "spikes": {date(2026, 10, 22): 4.0}}),
    ("acme-web-prod", "Cloud SQL", "projects/acme-web-prod/instances/app-db", "us-central1", "seconds", 38, {}),
    ("acme-web-prod", "Kubernetes Engine", "projects/acme-web-prod/locations/us-central1/clusters/prod-gke", "us-central1", "seconds", 44, {}),
]


def write_aws():
    header = [
        "bill/PayerAccountId", "lineItem/UsageAccountId", "lineItem/ProductCode", "lineItem/ResourceId",
        "product/region", "lineItem/UsageStartDate", "lineItem/UsageEndDate", "lineItem/UsageAmount",
        "pricing/unit", "lineItem/UnblendedCost", "lineItem/CurrencyCode",
    ]
    with open(OUT / "aws_billing.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for i, day in days():
            nxt = day + timedelta(days=1)
            for account, product, resource, region, unit, base, opts in AWS_LINES:
                w.writerow([
                    AWS_PAYER, account, product, resource, region,
                    f"{day.isoformat()}T00:00:00Z", f"{nxt.isoformat()}T00:00:00Z",
                    24, unit, amount(base, i, day, **opts), "USD",
                ])


def write_azure():
    header = [
        "BillingAccountId", "SubscriptionName", "MeterCategory", "ResourceId", "ResourceLocation",
        "Date", "Quantity", "UnitOfMeasure", "CostInBillingCurrency", "BillingCurrencyCode",
    ]
    with open(OUT / "azure_billing.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for i, day in days():
            for sub, meter, resource, location, unit, base, opts in AZURE_LINES:
                w.writerow([
                    AZ_BILLING, sub, meter, resource, location, day.strftime("%m/%d/%Y"),
                    24, unit, amount(base, i, day, **opts), "EUR",
                ])


def write_gcp():
    header = [
        "billing_account_id", "project.id", "service.description", "resource.name", "location.region",
        "usage_start_time", "usage_end_time", "usage.amount", "usage.unit", "cost", "currency",
    ]
    with open(OUT / "gcp_billing.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for i, day in days():
            nxt = day + timedelta(days=1)
            for project, service, resource, region, unit, base, opts in GCP_LINES:
                w.writerow([
                    GCP_BILLING, project, service, resource, region,
                    f"{day.isoformat()} 00:00:00 UTC", f"{nxt.isoformat()} 00:00:00 UTC",
                    86400, unit, amount(base, i, day, **opts), "USD",
                ])


def write_resources():
    """Inventory shaped like CloudQuery JSON output (one object per resource)."""
    sync = "2026-11-16T06:00:00Z"

    def res(table, rid, name, region, state, account):
        return {"_cq_table": table, "_cq_sync_time": sync, "id": rid, "name": name,
                "region": region, "state": state, "account_id": account}

    items = [
        res("aws_ec2_instances", "i-0a1b2c3d4e5f60001", "web-prod-1", "us-east-1", "running", AWS_PAYER),
        res("aws_ec2_instances", "i-0a1b2c3d4e5f60002", "web-prod-2", "us-east-1", "running", AWS_PAYER),
        res("aws_ec2_instances", "i-0a1b2c3d4e5f60003", "api-eu-1", "eu-west-1", "running", AWS_PAYER),
        res("aws_ec2_instances", "i-0deadbeef00000009", "legacy-batch", "us-east-1", "stopped", AWS_PAYER),
        res("aws_ec2_ebs_volumes", "vol-0f00ba47000000001", "old-data-volume", "us-east-1", "available", AWS_PAYER),
        res("aws_rds_instances", "arn:aws:rds:us-east-1:111122223333:db:orders-prod", "orders-prod", "us-east-1", "available", AWS_PAYER),
        res("aws_s3_buckets", "acme-prod-assets", "acme-prod-assets", "us-east-1", "", AWS_PAYER),
        res("aws_s3_buckets", "acme-logs", "acme-logs", "us-east-1", "", AWS_PAYER),
        res("azure_compute_virtual_machines", AZURE_LINES[0][2], "vm-web-01", "westeurope", "running", AZ_BILLING),
        res("azure_compute_virtual_machines", AZURE_LINES[1][2], "vm-web-02", "westeurope", "running", AZ_BILLING),
        res("azure_compute_virtual_machines", AZURE_LINES[2][2], "vm-dev-01", "northeurope", "running", AZ_BILLING),
        res("azure_compute_disks", AZURE_LINES[7][2], "disk-orphan-01", "northeurope", "unattached", AZ_BILLING),
        res("azure_network_public_ip_addresses", AZURE_LINES[8][2], "pip-unused-01", "northeurope", "unassociated", AZ_BILLING),
        res("azure_storage_accounts", AZURE_LINES[3][2], "contosoprodsa", "westeurope", "available", AZ_BILLING),
        res("gcp_compute_instances", GCP_LINES[0][2], "web-1", "us-central1", "RUNNING", GCP_BILLING),
        res("gcp_compute_instances", GCP_LINES[1][2], "web-2", "us-central1", "RUNNING", GCP_BILLING),
        res("gcp_compute_instances", GCP_LINES[2][2], "etl-old", "europe-west1", "TERMINATED", GCP_BILLING),
        res("gcp_storage_buckets", GCP_LINES[3][2], "acme-data-lake", "europe-west1", "", GCP_BILLING),
        res("gcp_sql_instances", GCP_LINES[5][2], "app-db", "us-central1", "RUNNABLE", GCP_BILLING),
        res("gcp_container_clusters", GCP_LINES[6][2], "prod-gke", "us-central1", "RUNNING", GCP_BILLING),
    ]
    (OUT / "cloudquery_resources.json").write_text(json.dumps(items, indent=2), encoding="utf-8")


def write_infracost():
    """Shaped like `infracost breakdown --format json` for infra/terraform/main.tf."""
    doc = {
        "version": "0.2",
        "currency": "USD",
        "projects": [{
            "name": "infra/terraform",
            "breakdown": {
                "resources": [
                    {"name": "aws_instance.web", "resourceType": "aws_instance", "monthlyCost": "67.74",
                     "costComponents": [
                         {"name": "Instance usage (Linux/UNIX, on-demand, t3.large)", "unit": "hours",
                          "monthlyQuantity": "730", "price": "0.0832", "monthlyCost": "60.74"},
                         {"name": "Storage (general purpose SSD, gp3)", "unit": "GB",
                          "monthlyQuantity": "87.5", "price": "0.08", "monthlyCost": "7.00"}]},
                    {"name": "aws_db_instance.orders", "resourceType": "aws_db_instance", "monthlyCost": "136.80",
                     "costComponents": [
                         {"name": "Database instance (on-demand, Single-AZ, db.t3.large)", "unit": "hours",
                          "monthlyQuantity": "730", "price": "0.156", "monthlyCost": "113.88"},
                         {"name": "Storage (general purpose SSD, gp3)", "unit": "GB",
                          "monthlyQuantity": "199.3", "price": "0.115", "monthlyCost": "22.92"}]},
                    {"name": "aws_s3_bucket.assets", "resourceType": "aws_s3_bucket", "monthlyCost": None,
                     "costComponents": [
                         {"name": "Storage (standard)", "unit": "GB", "monthlyQuantity": None,
                          "price": "0.023", "monthlyCost": None}]},
                ],
                "totalMonthlyCost": "204.54",
            },
        }],
        "totalMonthlyCost": "204.54",
    }
    (OUT / "infracost_sample.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")


if __name__ == "__main__":
    write_aws()
    write_azure()
    write_gcp()
    write_resources()
    write_infracost()
    print("Wrote simulated sample data to", OUT)
