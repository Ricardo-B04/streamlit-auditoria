import csv
import unittest
from auditoria import DATA_DIR, load_audit

payments, rules, findings, master = load_audit()


class AuditTest(unittest.TestCase):
    def test_detects_all_prepared_cases(self):
        checked = set()
        with (DATA_DIR / "casos_esperados.csv").open(encoding="utf-8", newline="") as file:
            for row in csv.DictReader(file):
                rule = row["ID"]
                keys = {key.strip() for key in row["Registros"].split(",")}
                candidates = [item for item in findings if item.rule == rule]
                with self.subTest(rule=rule, records=row["Registros"]):
                    if rule in {"A06", "A07", "A08"}:
                        before, after = [key.strip() for key in row["Registros"].split(",")]
                        flagged = {key for item in candidates for key in item.payment_ids}
                        self.assertNotIn(before, flagged)
                        self.assertIn(after, flagged)
                    elif rule in {"A05", "A16", "A20", "A21"}:
                        self.assertTrue(any(keys == set(item.vendor_ids) for item in candidates))
                    elif rule == "A24":
                        site, month = [key.strip() for key in row["Registros"].split(",")]
                        self.assertTrue(any(item.site == site and item.occurred_on.isoformat().startswith(month)
                                            for item in candidates))
                    elif rule in {"A19", "A23", "A28", "A29"}:
                        self.assertTrue(any(keys <= set(item.payment_ids + item.context_ids)
                                            and "910005397" in item.payment_ids for item in candidates))
                    else:
                        self.assertTrue(any(keys == set(item.payment_ids) for item in candidates))
                checked.add(rule)
        self.assertEqual(checked, set(rules))
        self.assertEqual(len(rules), 29)
        self.assertEqual(len(payments), 5399)
        self.assertEqual(len({item.id for item in findings}), len(findings))

