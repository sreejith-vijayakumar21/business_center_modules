from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import PARTNER_STATUS, FloorPlannerCase, partner_provider


@tagged("post_install", "-at_install")
class TestLinkAndStatus(FloorPlannerCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]
        cls.unit_a = Partner.create({"name": "Desk A-01", "company_id": cls.company.id})
        cls.unit_b = Partner.create({"name": "Desk A-02", "company_id": cls.company.id})
        cls.foreign_unit = Partner.create({"name": "Desk Z-99", "company_id": cls.other_company.id})

    def statuses(self):
        return {int(k): v for k, v in self.plan.fp_get_statuses()["objects"].items()}

    def link(self, client_key, partner, **kw):
        return self.obj(client_key=client_key, link_key="partner", link_res_id=partner.id, **kw)

    def test_core_works_without_provider(self):
        Registry = type(self.env["workspace.floor.link.registry"])
        with patch.object(Registry, "_get_provider_models", lambda self: []):
            self._check_core_without_provider()

    def _check_core_without_provider(self):
        result = self.save(self.plan, [self.obj()])
        self.assertEqual(result["providers"], [])
        statuses = self.statuses()
        self.assertEqual(statuses[result["id_map"]["c1"]]["status"], "unknown")
        with self.assertRaises(ValidationError):
            self.save(self.plan, [self.obj(link_key="partner", link_res_id=self.unit_a.id)])

    def test_each_desk_links_to_its_own_record(self):
        with partner_provider(self):
            result = self.save(self.plan, [self.link("a", self.unit_a), self.link("b", self.unit_b, x=100)])
            names = {o["link_name"] for o in result["objects"]}
            self.assertEqual(names, {"Desk A-01", "Desk A-02"})
            self.assertEqual(self.plan.linked_count, 2)
            # The designer never creates business records.
            self.assertEqual(self.env["res.partner"].search_count([("name", "like", "Desk A-")]), 2)

    def test_same_record_cannot_be_placed_twice(self):
        with partner_provider(self), self.assertRaises(ValidationError):
            self.save(self.plan, [self.link("a", self.unit_a), self.link("b", self.unit_a, x=100)])

    def test_rejects_invalid_links(self):
        with partner_provider(self):
            cases = [
                self.obj(link_key="res.users", link_res_id=1),               # not a registered provider
                self.obj(link_key="partner", link_res_id=99999999),          # missing record
                self.obj(link_key="partner", link_res_id=self.foreign_unit.id),  # other company
                self.obj(object_type="wall", link_key="partner", link_res_id=self.unit_a.id),  # not rentable
                self.obj(link_key="partner", link_res_id="1"),
            ]
            for vals in cases:
                with self.subTest(vals=vals), self.assertRaises(ValidationError):
                    self.save(self.plan, [vals])

    def test_statuses_and_zone_summary(self):
        with partner_provider(self):
            result = self.save(self.plan, [
                self.obj(client_key="zone", object_type="coworking_zone", x=0, y=0, width=400, height=300),
                self.link("a", self.unit_a, x=20, y=20),
                self.link("b", self.unit_b, x=120, y=20),
                self.obj(client_key="free", x=600, y=600),  # unlinked, outside the zone
            ])
            ids = result["id_map"]
            PARTNER_STATUS.update({self.unit_a.id: "available", self.unit_b.id: "occupied"})
            statuses = self.statuses()
            self.assertEqual(statuses[ids["a"]]["status"], "available")
            self.assertEqual(statuses[ids["b"]]["status"], "occupied")
            self.assertEqual(statuses[ids["free"]]["status"], "unknown")
            self.assertEqual(statuses[ids["zone"]], {"status": "partial", "available": 1, "total": 2})

            # A booking change shows up on the next refresh (nothing is cached).
            PARTNER_STATUS[self.unit_b.id] = "available"
            zone = self.statuses()[ids["zone"]]
            self.assertEqual(zone, {"status": "available", "available": 2, "total": 2})

    def test_unsupported_provider_status_becomes_unknown(self):
        with partner_provider(self):
            result = self.save(self.plan, [self.link("a", self.unit_a)])
            PARTNER_STATUS[self.unit_a.id] = "partial"  # only zones may be partial
            status = self.statuses()[result["id_map"]["a"]]
            self.assertEqual(status["status"], "unknown")
            PARTNER_STATUS[self.unit_a.id] = "<script>"
            status = self.statuses()[result["id_map"]["a"]]
            self.assertEqual(status["status"], "unknown")

    def test_open_linked_record_and_search(self):
        with partner_provider(self):
            result = self.save(self.plan, [self.link("a", self.unit_a)])
            action = self.plan.fp_open_linked_record(result["id_map"]["a"])
            self.assertEqual((action["res_model"], action["res_id"]), ("res.partner", self.unit_a.id))
            found = self.plan.fp_search_link_targets("partner", "Desk")
            found_ids = {row["id"] for row in found}
            self.assertIn(self.unit_b.id, found_ids)
            self.assertNotIn(self.foreign_unit.id, found_ids, "other-company units are not offered")
            self.assertTrue(next(r for r in found if r["id"] == self.unit_a.id)["already_placed"])
            # An object id from another plan never opens anything.
            other = self.env["workspace.floor.plan"].create({"name": "L2"})
            self.assertFalse(other.fp_open_linked_record(result["id_map"]["a"]))

    def test_restricted_link_name_not_leaked(self):
        with partner_provider(self):
            result = self.save(self.plan, [self.link("a", self.unit_a)])
            # Simulate the record moving to a company the user cannot see.
            self.unit_a.company_id = self.other_company
            obj = self.plan.with_user(self.viewer).fp_load_layout()["objects"][0]
            self.assertTrue(obj["link_restricted"])
            self.assertNotIn("Desk A-01", obj["link_name"])
            self.assertFalse(self.plan.with_user(self.viewer).fp_open_linked_record(result["id_map"]["a"]))
