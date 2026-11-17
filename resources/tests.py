import json

from ingestion.tests import ImportTestCase
from resources.importer import import_inventory
from resources.models import CloudResource

INSTANCE = {
    "_cq_table": "aws_ec2_instances",
    "_cq_sync_time": "2026-07-20T06:00:00Z",
    "account_id": "aws-001",
    "instance_id": "i-0001",
    "region": "us-east-1",
    "state": "running",
    "tags": {"Name": "web-1"},
}


class ImportInventoryTests(ImportTestCase):
    def test_json_array(self):
        imported, skipped = import_inventory(self.user, json.dumps([INSTANCE]))
        self.assertEqual((imported, skipped), (1, 0))
        res = CloudResource.objects.get(user=self.user)
        self.assertEqual(res.provider, "aws")
        self.assertEqual(res.resource_id, "i-0001")
        self.assertEqual(res.resource_type, "aws_ec2_instances")
        self.assertEqual(res.resource_name, "web-1")
        self.assertEqual(res.region, "us-east-1")
        self.assertEqual(res.status, "running")
        self.assertEqual(res.cloud_account, self.accounts["aws"])
        self.assertEqual(res.last_seen_at.isoformat(), "2026-07-20T06:00:00+00:00")

    def test_json_lines(self):
        second = dict(INSTANCE, instance_id="i-0002")
        text = json.dumps(INSTANCE) + "\n" + json.dumps(second) + "\n"
        self.assertEqual(import_inventory(self.user, text), (2, 0))

    def test_wrapped_in_resources_key(self):
        text = json.dumps({"resources": [INSTANCE]})
        self.assertEqual(import_inventory(self.user, text), (1, 0))

    def test_unusable_items_are_skipped(self):
        items = [
            INSTANCE,
            "just a string",
            {"_cq_table": "aws_ec2_instances"},  # no id
            {"_cq_table": "oracle_vm", "id": "x-1"},  # unknown provider
        ]
        self.assertEqual(import_inventory(self.user, json.dumps(items)), (1, 3))
        self.assertEqual(CloudResource.objects.count(), 1)

    def test_reimport_updates_instead_of_duplicating(self):
        import_inventory(self.user, json.dumps([INSTANCE]))
        import_inventory(self.user, json.dumps([dict(INSTANCE, state="stopped")]))
        res = CloudResource.objects.get(user=self.user)
        self.assertEqual(res.status, "stopped")

    def test_bad_files(self):
        with self.assertRaisesMessage(ValueError, "empty"):
            import_inventory(self.user, "   ")
        with self.assertRaisesMessage(ValueError, "not valid JSON"):
            import_inventory(self.user, "{broken")
        with self.assertRaisesMessage(ValueError, "JSON array"):
            import_inventory(self.user, "42")
