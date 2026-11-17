import json

from django.test import SimpleTestCase

from estimates.parser import parse_infracost


def infracost(total="100.50", resources=None):
    payload = {
        "currency": "USD",
        "projects": [
            {
                "name": "infra/terraform",
                "breakdown": {
                    "resources": resources
                    if resources is not None
                    else [
                        {
                            "name": "aws_instance.web",
                            "resourceType": "aws_instance",
                            "monthlyCost": "60.50",
                            "costComponents": [
                                {"name": "Instance usage", "unit": "hours",
                                 "monthlyQuantity": "730", "price": "0.0832",
                                 "monthlyCost": "60.50"},
                            ],
                        },
                        {
                            "name": "aws_db_instance.main",
                            "resourceType": "aws_db_instance",
                            "monthlyCost": "40.00",
                        },
                    ]
                },
            }
        ],
    }
    if total is not None:
        payload["totalMonthlyCost"] = total
    return json.dumps(payload)


class ParseInfracostTests(SimpleTestCase):
    def test_valid_file(self):
        result = parse_infracost(infracost())
        self.assertAlmostEqual(float(result["total"]), 100.50, places=2)
        self.assertEqual(result["currency"], "USD")
        names = [r["name"] for r in result["breakdown"]]
        self.assertEqual(names, ["aws_instance.web", "aws_db_instance.main"])
        self.assertAlmostEqual(float(result["breakdown"][0]["monthly_cost"]), 60.50, places=2)
        self.assertEqual(len(result["breakdown"][0]["components"]), 1)

    def test_total_falls_back_to_sum_of_resources(self):
        result = parse_infracost(infracost(total=None))
        self.assertAlmostEqual(float(result["total"]), 100.50, places=2)

    def test_no_costs_gives_no_total(self):
        result = parse_infracost(infracost(total=None, resources=[]))
        self.assertIsNone(result["total"])

    def test_invalid_json(self):
        with self.assertRaisesMessage(ValueError, "not valid JSON"):
            parse_infracost("{not json")

    def test_wrong_shape(self):
        with self.assertRaisesMessage(ValueError, "Infracost"):
            parse_infracost(json.dumps({"hello": "world"}))
        with self.assertRaisesMessage(ValueError, "Infracost"):
            parse_infracost(json.dumps([1, 2, 3]))
