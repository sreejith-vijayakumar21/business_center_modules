from datetime import date, datetime

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestBusinessCenterLayout(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        env.user.tz = "UTC"
        cls.center = env["business.center"].create({
            "name": "ABC Business Center", "code": "ABC", "email": "abc@example.com",
            "manager_id": env.user.id,
        })
        cls.floor = env["business.center.floor"].create({"name": "F0", "center_id": cls.center.id})
        cls.other_floor = env["business.center.floor"].create({"name": "F1", "center_id": cls.center.id})
        Space = env["business.center.space"]
        common = {"center_id": cls.center.id, "floor_id": cls.floor.id, "monthly_rent": 100,
                  "hourly_rate": 10, "min_booking_hour": 8, "max_booking_hour": 20}
        cls.office_free = Space.create({**common, "name": "Office 101", "area_sqm": 12})
        cls.office_busy = Space.create({**common, "name": "Office 102"})
        cls.coworking = Space.create({**common, "name": "Cowork A", "is_coworking": True})
        cls.room = Space.create({**common, "name": "Board Room", "space_type": "meeting_room", "capacity": 6})
        cls.other_office = Space.create({**common, "name": "Office 201", "floor_id": cls.other_floor.id})
        Desk = env["business.center.desk"]
        cls.desks = Desk.create([
            {"name": f"D{i}", "space_id": cls.coworking.id} for i in range(1, 5)
        ])
        # Leave draft, then set operational states (only "state" may change now).
        (cls.office_free | cls.office_busy | cls.coworking | cls.room | cls.other_office).write({"state": "available"})
        cls.office_busy.write({"state": "occupied"})
        cls.desks.write({"state": "available"})
        cls.desks[0].write({"state": "occupied"})
        cls.desks[1].write({"state": "maintenance"})

    def statuses(self, plan, at=None):
        result = plan.fp_get_statuses(at)
        return result, {int(k): v["status"] for k, v in result["objects"].items()}

    def test_floor_counts(self):
        floor = self.floor
        self.assertEqual((floor.office_count, floor.office_available_count), (2, 1))
        self.assertEqual((floor.desk_count, floor.desk_available_count), (4, 2))
        self.assertEqual((floor.meeting_room_count, floor.meeting_room_available_count), (1, 1))
        self.assertEqual((floor.unit_count, floor.unit_available_count), (7, 4))

    def test_first_open_creates_prefilled_layout_then_live_view(self):
        action = self.floor.action_open_floor_layout()
        self.assertEqual(action["tag"], "workspace_floor_planner.editor")
        plan = self.floor.floor_plan_id
        self.assertTrue(plan)
        self.assertEqual(plan.bc_floor_id, self.floor)
        linked = plan.object_ids.filtered("link_key")
        self.assertEqual(len(linked), 7, "every office, desk and meeting room is placed once")
        self.assertEqual(len(plan.object_ids.filtered(lambda o: o.object_type == "coworking_zone")), 1)
        self.assertFalse(linked.filtered(lambda o: o.link_res_id == self.other_office.id
                                         and o.link_key == "bc_office"), "other floors are not included")
        # Second open goes to the live view; no second layout is created.
        action = self.floor.action_open_floor_layout()
        self.assertEqual(action["tag"], "workspace_floor_planner.viewer")
        self.assertEqual(len(self.floor.floor_plan_ids), 1)

    def test_statuses_follow_business_center_state(self):
        self.floor.action_open_floor_layout()
        plan = self.floor.floor_plan_id
        result, status = self.statuses(plan)
        by_link = {(o.link_key, o.link_res_id): status[o.id] for o in plan.object_ids.filtered("link_key")}
        self.assertEqual(by_link[("bc_office", self.office_free.id)], "available")
        self.assertEqual(by_link[("bc_office", self.office_busy.id)], "occupied")
        self.assertEqual(by_link[("bc_desk", self.desks[0].id)], "occupied")
        self.assertEqual(by_link[("bc_desk", self.desks[1].id)], "maintenance")
        self.assertEqual(by_link[("bc_meeting_room", self.room.id)], "available")
        zone = plan.object_ids.filtered(lambda o: o.object_type == "coworking_zone")
        self.assertEqual(result["objects"][str(zone.id)], {"status": "partial", "available": 2, "total": 4})
        summary = result["summary"]
        self.assertEqual(summary["total"], 7)
        self.assertEqual(
            (summary["available"], summary["occupied"], summary["maintenance"]), (4, 2, 1))
        self.assertEqual(summary["unplaced"], 0)

        # A state change in Business Center shows on the next refresh.
        self.office_free.write({"state": "maintenance"})
        _result, status = self.statuses(plan)
        obj = plan.object_ids.filtered(lambda o: o.link_res_id == self.office_free.id and o.link_key == "bc_office")
        self.assertEqual(status[obj.id], "maintenance")

    def test_unplaced_units_are_counted(self):
        self.floor.action_open_floor_layout()
        plan = self.floor.floor_plan_id
        plan.object_ids.filtered(lambda o: o.link_key == "bc_desk")[:2].unlink()
        result, _status = self.statuses(plan)
        self.assertEqual(result["summary"]["total"], 7)
        self.assertEqual(result["summary"]["unplaced"], 2)

    def test_link_rules(self):
        self.floor.action_open_floor_layout()
        plan = self.floor.floor_plan_id
        office_obj = plan.object_ids.filtered(lambda o: o.link_key == "bc_office")[:1]
        # A meeting room cannot be linked through the office provider.
        with self.assertRaises(ValidationError):
            office_obj.link_res_id = self.room.id
        # Search only offers units of this floor and of the right type.
        found = {r["id"] for r in plan.fp_search_link_targets("bc_office", "Office")}
        self.assertIn(self.office_free.id, found)
        self.assertNotIn(self.other_office.id, found)
        self.assertNotIn(self.room.id, found)
        # Desks cannot be linked to an office shape.
        with self.assertRaises(ValidationError):
            office_obj.write({"link_key": "bc_desk", "link_res_id": self.desks[2].id})

    def test_meeting_room_bookings(self):
        tenant = self.env["res.partner"].create({"name": "Tenant"})
        contract = self.env["business.center.contract"].create({
            "partner_id": tenant.id, "center_id": self.center.id,
            "date_start": date(2026, 1, 1), "date_end": date(2026, 12, 31),
        })
        day = date(2026, 3, 10)
        for start, end in ((9, 11), (14, 15)):
            booking = self.env["business.center.booking"].create({
                "contract_id": contract.id, "meeting_room_id": self.room.id,
                "booking_date": day, "start_time": start, "end_time": end,
            })
            booking.with_context(bc_state_from_action=True).write({"state": "confirmed"})
        provider = self.env["workspace.floor.link.provider.bc_meeting_room"]
        status_at = lambda hour: provider._fp_get_statuses(self.room, datetime(2026, 3, 10, hour))[self.room.id]
        self.assertEqual(status_at(10), "occupied")
        self.assertEqual(status_at(12), "reserved")
        self.assertEqual(status_at(16), "available")
        self.room.write({"state": "maintenance"})
        self.assertEqual(status_at(10), "maintenance")

    def test_meeting_room_time_mapping(self):
        provider = self.env["workspace.floor.link.provider.bc_meeting_room"]
        self.env.user.tz = "Asia/Kolkata"
        day, hour = provider._local_moment(datetime(2026, 1, 1, 4, 30))
        self.assertEqual((day, hour), (date(2026, 1, 1), 10.0))
        self.assertTrue(provider._fp_is_time_dependent())

    def test_user_without_floor_planner_rights_cannot_create_layout(self):
        user = new_test_user(self.env, login="bc_plain", groups="base.group_user")
        floor = self.other_floor.with_user(user)
        with self.assertRaises(Exception):
            floor.action_open_floor_layout()

    def test_bc_user_gets_viewer_rights(self):
        user = new_test_user(self.env, login="bc_staff", groups="business_center.group_bc_user")
        self.assertTrue(user.has_group("workspace_floor_planner.group_floor_planner_viewer"))
        self.assertFalse(user.has_group("workspace_floor_planner.group_floor_planner_user"))
        self.floor.action_open_floor_layout()
        layout = self.floor.floor_plan_id.with_user(user).fp_load_layout()
        self.assertFalse(layout["plan"]["can_edit"])
        with self.assertRaises(UserError):
            self.other_floor.with_user(user).action_open_floor_layout()
