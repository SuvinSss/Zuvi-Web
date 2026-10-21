"""Tickets, complaints, feedback: roles, privacy, workflow, SLA, attachments."""
from datetime import timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from accounts.models import Role
from customers.models import RegistrationSource
from customers.services import create_customer_with_user
from core.models import AuditEvent
from deliveries import services as delivery_services
from deliveries.tests import DROP_LAT, DROP_LON, DeliveryBase, jpeg
from notifications.models import Notification

from . import services, sla
from .models import Complaint, ComplaintStatus, Ticket, TicketStatus

User = get_user_model()


def pdf(name="evidence.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF", content_type="application/pdf")


class SupportBase(DeliveryBase):
    def setUp(self):
        super().setUp()
        self.agent = self.staff_user("agent1", Role.SUPPORT_AGENT)
        self.agent2 = self.staff_user("agent2", Role.SUPPORT_AGENT)
        self.supervisor = self.staff_user("super1", Role.SUPPORT_SUPERVISOR)

    def staff_user(self, name, role):
        return User.objects.create_user(username=name, email=f"{name}@example.com", password="x", role=role,
                                        phone_number=f"9200{abs(hash(name)) % 1000000:06d}")

    def as_(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def other_customer(self, name="sup-other"):
        return create_customer_with_user(
            user_data={"username": name, "email": f"{name}@example.com", "first_name": "Other", "last_name": "Person",
                       "phone_number": f"9300{abs(hash(name)) % 1000000:06d}", "password": "secure-password-123"},
            registration_source=RegistrationSource.WEBSITE)[1]

    def ticket(self, **extra):
        data = {"category": "ORDER", "subject": "Where is my order", "description": "It is late", **extra}
        response = self.as_(self.customer_user).post("/api/v1/support/tickets/", data, format="json")
        assert response.status_code == 201, response.content
        return response.json()

    def delivered(self):
        partner = self.make_partner("support-rider")
        delivery = self.accepted_delivery(partner)
        self.pickup(delivery, partner)
        delivery_services.complete_delivery(delivery.pk, partner, photos=[jpeg()], latitude=DROP_LAT, longitude=DROP_LON)
        return partner, delivery

    def complaint(self, **extra):
        data = {"against_type": "STORE", "category": "QUALITY", "description": "The vegetables were rotten.",
                "order": self.order.pk, "store": self.store.pk, **extra}
        response = self.as_(self.customer_user).post("/api/v1/support/complaints/", data, format="json")
        assert response.status_code == 201, response.content
        return response.json()


class TicketTests(SupportBase):
    def test_create_sets_reference_sla_and_notifies(self):
        data = self.ticket(order=self.order.pk)
        self.assertTrue(data["reference"].startswith("TKT-"))
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.status, TicketStatus.OPEN)
        self.assertEqual(ticket.first_response_due - ticket.created_at, timedelta(hours=8))
        self.assertEqual(ticket.resolution_due - ticket.created_at, timedelta(hours=48))
        self.assertTrue(Notification.objects.filter(recipient=self.supervisor, kind="TICKET_CREATED").exists())
        self.assertIsNone(data["sla"])  # SLA is for staff only

    def test_cannot_attach_someone_elses_order(self):
        other = self.other_customer()
        response = self.as_(other).post("/api/v1/support/tickets/", {"subject": "x", "description": "y", "order": self.order.pk}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_requester_sees_only_own_tickets(self):
        self.ticket()
        other = self.other_customer()
        self.assertEqual(self.as_(other).get("/api/v1/support/tickets/").json()["count"], 0)
        ticket = Ticket.objects.get()
        self.assertEqual(self.as_(other).get(f"/api/v1/support/tickets/{ticket.pk}/").status_code, 404)
        self.assertEqual(self.as_(other).post(f"/api/v1/support/tickets/{ticket.pk}/messages/", {"body": "hi"}, format="json").status_code, 404)

    def test_internal_notes_are_invisible_to_requester(self):
        ticket = Ticket.objects.get(pk=self.ticket()["id"])
        agent = self.as_(self.agent)
        self.assertEqual(agent.post(f"/api/v1/support/tickets/{ticket.pk}/assign/", {}, format="json").status_code, 200)
        agent.post(f"/api/v1/support/tickets/{ticket.pk}/messages/", {"body": "Customer is a repeat caller", "is_internal": True}, format="json")
        agent.post(f"/api/v1/support/tickets/{ticket.pk}/messages/", {"body": "Looking into it now"}, format="json")
        mine = self.as_(self.customer_user).get(f"/api/v1/support/tickets/{ticket.pk}/").json()
        bodies = [m["body"] for m in mine["messages"]]
        self.assertEqual(bodies, ["Looking into it now"])
        self.assertNotIn("repeat caller", str(mine))
        self.assertEqual(mine["assigned_to"], {"name": "Support team"})  # agent identity is not exposed
        staff = agent.get(f"/api/v1/support/tickets/{ticket.pk}/").json()
        self.assertEqual(len(staff["messages"]), 2)

    def test_customer_cannot_post_internal_note(self):
        ticket = self.ticket()
        response = self.as_(self.customer_user).post(f"/api/v1/support/tickets/{ticket['id']}/messages/", {"body": "x", "is_internal": True}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_first_staff_reply_records_response_time_and_moves_in_progress(self):
        ticket = Ticket.objects.get(pk=self.ticket()["id"])
        self.as_(self.agent).post(f"/api/v1/support/tickets/{ticket.pk}/messages/", {"body": "On it"}, format="json")
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.first_responded_at)
        self.assertEqual((ticket.status, ticket.assigned_to), (TicketStatus.IN_PROGRESS, self.agent))
        self.assertEqual(services.ticket_sla(ticket)["first_response"], "met")
        self.assertTrue(Notification.objects.filter(recipient=self.customer_user, kind="TICKET_REPLY").exists())

    def test_agents_work_only_unassigned_or_own_tickets(self):
        ticket = Ticket.objects.get(pk=self.ticket()["id"])
        self.as_(self.agent).post(f"/api/v1/support/tickets/{ticket.pk}/assign/", {}, format="json")
        rival = self.as_(self.agent2)
        self.assertEqual(rival.get(f"/api/v1/support/tickets/{ticket.pk}/").status_code, 404)
        self.assertEqual(rival.post(f"/api/v1/support/tickets/{ticket.pk}/messages/", {"body": "mine now"}, format="json").status_code, 404)
        self.assertEqual(rival.get("/api/v1/support/tickets/").json()["count"], 0)
        self.assertEqual(self.as_(self.supervisor).get(f"/api/v1/support/tickets/{ticket.pk}/").status_code, 200)

    def test_only_supervisors_assign_to_other_agents(self):
        ticket = Ticket.objects.get(pk=self.ticket()["id"])
        denied = self.as_(self.agent).post(f"/api/v1/support/tickets/{ticket.pk}/assign/", {"assignee": self.agent2.pk}, format="json")
        self.assertEqual(denied.status_code, 403)
        ok = self.as_(self.supervisor).post(f"/api/v1/support/tickets/{ticket.pk}/assign/", {"assignee": self.agent2.pk}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertTrue(Notification.objects.filter(recipient=self.agent2, kind="TICKET_ASSIGNED").exists())
        self.assertTrue(AuditEvent.objects.filter(action="ticket.assign", actor=self.supervisor).exists())
        bad = self.as_(self.supervisor).post(f"/api/v1/support/tickets/{ticket.pk}/assign/", {"assignee": self.customer_user.pk}, format="json")
        self.assertEqual(bad.status_code, 400)

    def test_status_workflow_and_invalid_transitions(self):
        ticket = Ticket.objects.get(pk=self.ticket()["id"])
        agent = self.as_(self.agent)
        agent.post(f"/api/v1/support/tickets/{ticket.pk}/assign/", {}, format="json")
        self.assertEqual(agent.post(f"/api/v1/support/tickets/{ticket.pk}/status/", {"status": "CLOSED"}, format="json").status_code, 400)
        self.assertEqual(agent.post(f"/api/v1/support/tickets/{ticket.pk}/status/", {"status": "WAITING_CUSTOMER"}, format="json").status_code, 200)
        reply = self.as_(self.customer_user).post(f"/api/v1/support/tickets/{ticket.pk}/messages/", {"body": "Here is the info"}, format="json")
        self.assertEqual(reply.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.IN_PROGRESS)
        self.assertEqual(agent.post(f"/api/v1/support/tickets/{ticket.pk}/status/", {"status": "RESOLVED"}, format="json").status_code, 200)
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.resolved_at)
        reopen = self.as_(self.customer_user).post(f"/api/v1/support/tickets/{ticket.pk}/status/", {"status": "OPEN"}, format="json")
        self.assertEqual(reopen.status_code, 200)
        self.as_(self.customer_user).post(f"/api/v1/support/tickets/{ticket.pk}/status/", {"status": "CLOSED"}, format="json")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.CLOSED)
        self.assertEqual(self.as_(self.customer_user).post(f"/api/v1/support/tickets/{ticket.pk}/messages/", {"body": "more"}, format="json").status_code, 400)

    def test_requester_cannot_resolve_or_prioritise(self):
        ticket = self.ticket()
        api = self.as_(self.customer_user)
        self.assertEqual(api.post(f"/api/v1/support/tickets/{ticket['id']}/status/", {"status": "RESOLVED"}, format="json").status_code, 400)
        self.assertEqual(api.post(f"/api/v1/support/tickets/{ticket['id']}/priority/", {"priority": "URGENT"}, format="json").status_code, 403)
        self.assertEqual(api.post(f"/api/v1/support/tickets/{ticket['id']}/escalate/", {"reason": "x"}, format="json").status_code, 403)

    def test_priority_change_recomputes_sla_and_escalation_notifies_supervisors(self):
        ticket = Ticket.objects.get(pk=self.ticket()["id"])
        agent = self.as_(self.agent)
        agent.post(f"/api/v1/support/tickets/{ticket.pk}/assign/", {}, format="json")
        agent.post(f"/api/v1/support/tickets/{ticket.pk}/priority/", {"priority": "URGENT"}, format="json")
        ticket.refresh_from_db()
        self.assertEqual(ticket.first_response_due - ticket.created_at, timedelta(hours=1))
        self.assertEqual(agent.post(f"/api/v1/support/tickets/{ticket.pk}/escalate/", {"reason": ""}, format="json").status_code, 400)
        self.assertEqual(agent.post(f"/api/v1/support/tickets/{ticket.pk}/escalate/", {"reason": "Needs refund approval"}, format="json").status_code, 200)
        ticket.refresh_from_db()
        self.assertTrue(ticket.escalated)
        self.assertTrue(Notification.objects.filter(recipient=self.supervisor, title__contains="escalated").exists())
        self.assertEqual(agent.post(f"/api/v1/support/tickets/{ticket.pk}/escalate/", {"reason": "again"}, format="json").status_code, 400)

    def test_html_is_stripped(self):
        data = self.ticket(subject="<script>x</script>Help", description="<b>bold</b> text")
        self.assertEqual(data["subject"], "xHelp")
        self.assertNotIn("<", data["description"])

    def test_attachments_private_and_validated(self):
        response = self.as_(self.customer_user).post(
            "/api/v1/support/tickets/", {"subject": "Photo", "description": "see attached", "attachments": [jpeg(), pdf()]}, format="multipart")
        self.assertEqual(response.status_code, 201, response.content)
        ticket = Ticket.objects.get()
        files = list(ticket.attachments.order_by("pk"))
        self.assertEqual([f.content_type for f in files], ["image/jpeg", "application/pdf"])
        url = f"/api/v1/support/attachments/ticket/{files[0].pk}/file/"
        self.assertEqual(self.as_(self.customer_user).get(url).status_code, 200)
        self.assertEqual(self.as_(self.supervisor).get(url).status_code, 200)
        self.assertEqual(self.as_(self.other_customer()).get(url).status_code, 404)
        anon = APIClient()
        self.assertIn(anon.get(url).status_code, (401, 403))
        bad = SimpleUploadedFile("x.exe", b"MZ\x90\x00not a document", content_type="application/pdf")
        rejected = self.as_(self.customer_user).post("/api/v1/support/tickets/", {"subject": "s", "description": "d", "attachments": [bad]}, format="multipart")
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(Ticket.objects.count(), 1)  # nothing half-created

    def test_internal_attachment_hidden_from_requester(self):
        ticket = Ticket.objects.get(pk=self.ticket()["id"])
        agent = self.as_(self.agent)
        agent.post(f"/api/v1/support/tickets/{ticket.pk}/assign/", {}, format="json")
        agent.post(f"/api/v1/support/tickets/{ticket.pk}/messages/", {"body": "internal doc", "is_internal": "true", "attachments": [pdf()]}, format="multipart")
        attachment = ticket.attachments.get()
        self.assertTrue(attachment.is_internal)
        url = f"/api/v1/support/attachments/ticket/{attachment.pk}/file/"
        self.assertEqual(self.as_(self.customer_user).get(url).status_code, 404)
        self.assertEqual(agent.get(url).status_code, 200)

    def test_sla_reminders_sent_once(self):
        ticket = Ticket.objects.get(pk=self.ticket()["id"])
        Ticket.objects.filter(pk=ticket.pk).update(created_at=timezone.now() - timedelta(hours=9),
                                                   first_response_due=timezone.now() - timedelta(hours=1))
        first = services.send_sla_reminders()
        self.assertGreaterEqual(first["breached"], 1)
        before = Notification.objects.count()
        again = services.send_sla_reminders()
        self.assertEqual(again, {"due_soon": 0, "breached": 0})
        self.assertEqual(Notification.objects.count(), before)

    def test_sla_states(self):
        start = timezone.now() - timedelta(hours=10)
        due = start + timedelta(hours=8)
        self.assertEqual(sla.state(due, None, start=start), "breached")
        self.assertEqual(sla.state(due, due - timedelta(hours=1), start=start), "met")
        self.assertEqual(sla.state(due, due + timedelta(hours=1), start=start), "missed")
        now = timezone.now()
        self.assertEqual(sla.state(now + timedelta(hours=1), None, start=now - timedelta(hours=7)), "due_soon")
        self.assertEqual(sla.state(now + timedelta(hours=7), None, start=now), "ok")

    def test_management_command_runs(self):
        from io import StringIO
        out = StringIO()
        call_command("send_sla_reminders", stdout=out)
        self.assertIn("SLA reminders sent", out.getvalue())

    def test_unauthenticated_and_non_role_users_get_nothing(self):
        self.assertIn(APIClient().get("/api/v1/support/tickets/").status_code, (401, 403))
        self.assertEqual(self.as_(self.customer_user).get("/api/v1/support/agents/").status_code, 403)
        self.assertEqual(self.as_(self.agent).get("/api/v1/support/summary/").status_code, 403)
        self.assertEqual(self.as_(self.supervisor).get("/api/v1/support/summary/").status_code, 200)


class ComplaintTests(SupportBase):
    def setUp(self):
        super().setUp()
        self.partner, self.delivery = self.delivered()

    def test_submit_complaint_against_store_with_sla(self):
        data = self.complaint()
        self.assertTrue(data["reference"].startswith("CMP-"))
        self.assertEqual((data["status"], data["severity"]), ("SUBMITTED", "HIGH"))
        complaint = Complaint.objects.get()
        self.assertEqual(complaint.acknowledge_due - complaint.created_at, timedelta(hours=4))
        self.assertEqual(complaint.events.get().kind, "SUBMITTED")
        self.assertTrue(Notification.objects.filter(recipient=self.supervisor, kind="COMPLAINT_SUBMITTED").exists())

    def test_complaint_must_reference_own_order_and_related_party(self):
        other_store = self.create_store(name="Unrelated Store")
        api = self.as_(self.customer_user)
        base = {"against_type": "STORE", "category": "QUALITY", "description": "Something went wrong here.", "order": self.order.pk}
        self.assertEqual(api.post("/api/v1/support/complaints/", {**base, "store": other_store.pk}, format="json").status_code, 400)
        self.assertEqual(api.post("/api/v1/support/complaints/", {**base, "store": self.store.pk, "order": None}, format="json").status_code, 400)
        stranger = self.make_partner("not-involved")
        self.assertEqual(api.post("/api/v1/support/complaints/", {**base, "against_type": "DELIVERY_PARTNER", "partner": stranger.pk}, format="json").status_code, 400)
        ok = api.post("/api/v1/support/complaints/", {**base, "against_type": "DELIVERY_PARTNER", "partner": self.partner.pk, "category": "BEHAVIOUR"}, format="json")
        self.assertEqual(ok.status_code, 201, ok.content)
        thief = self.as_(self.other_customer())
        self.assertEqual(thief.post("/api/v1/support/complaints/", {**base, "store": self.store.pk}, format="json").status_code, 400)
        short = api.post("/api/v1/support/complaints/", {**base, "store": self.store.pk, "description": "bad"}, format="json")
        self.assertEqual(short.status_code, 400)

    def test_platform_complaint_needs_no_order(self):
        response = self.as_(self.customer_user).post("/api/v1/support/complaints/", {
            "against_type": "PLATFORM", "category": "OTHER", "description": "The app charged me twice somewhere."}, format="json")
        self.assertEqual(response.status_code, 201, response.content)

    def test_store_and_partner_cannot_see_complaints_about_them(self):
        complaint = self.complaint()
        for user in (self.store_user, self.partner.user):
            api = self.as_(user)
            self.assertEqual(api.get("/api/v1/support/complaints/").json()["count"], 0)
            self.assertEqual(api.get(f"/api/v1/support/complaints/{complaint['id']}/").status_code, 404)
        self.assertEqual(self.as_(self.other_customer()).get(f"/api/v1/support/complaints/{complaint['id']}/").status_code, 404)

    def test_full_lifecycle_with_private_notes_and_timeline(self):
        complaint = self.complaint()
        cid = complaint["id"]
        agent = self.as_(self.agent)
        customer = self.as_(self.customer_user)
        self.assertEqual(agent.post(f"/api/v1/support/complaints/{cid}/assign/", {}, format="json").status_code, 200)
        self.assertEqual(Complaint.objects.get().status, ComplaintStatus.UNDER_REVIEW)
        agent.post(f"/api/v1/support/complaints/{cid}/comments/", {"body": "Store has history of this", "is_internal": True}, format="json")
        self.assertEqual(agent.post(f"/api/v1/support/complaints/{cid}/request-info/", {"message": "Please send a photo"}, format="json").status_code, 200)
        self.assertEqual(Complaint.objects.get().status, ComplaintStatus.INFO_REQUESTED)
        customer.post(f"/api/v1/support/complaints/{cid}/comments/", {"body": "Photo attached", "attachments": [jpeg()]}, format="multipart")
        self.assertEqual(Complaint.objects.get().status, ComplaintStatus.UNDER_REVIEW)
        self.assertEqual(agent.post(f"/api/v1/support/complaints/{cid}/resolve/", {"resolution": ""}, format="json").status_code, 400)
        done = agent.post(f"/api/v1/support/complaints/{cid}/resolve/", {"resolution": "Refunded the vegetables."}, format="json")
        self.assertEqual(done.status_code, 200, done.content)
        view = customer.get(f"/api/v1/support/complaints/{cid}/").json()
        kinds = [e["kind"] for e in view["timeline"]]
        self.assertNotIn("NOTE", kinds)
        self.assertNotIn("history", str(view))
        self.assertIn("INFO_REQUEST", kinds)
        self.assertEqual(view["resolution"], "Refunded the vegetables.")
        self.assertTrue(Notification.objects.filter(recipient=self.customer_user, kind="COMPLAINT_RESOLVED").exists())
        staff_kinds = [e["kind"] for e in agent.get(f"/api/v1/support/complaints/{cid}/").json()["timeline"]]
        self.assertIn("NOTE", staff_kinds)
        self.assertEqual(services.complaint_sla(Complaint.objects.get())["acknowledgement"], "met")

    def test_escalation_requires_supervisor_to_resolve(self):
        cid = self.complaint()["id"]
        agent, supervisor = self.as_(self.agent), self.as_(self.supervisor)
        agent.post(f"/api/v1/support/complaints/{cid}/assign/", {}, format="json")
        self.assertEqual(agent.post(f"/api/v1/support/complaints/{cid}/escalate/", {"reason": ""}, format="json").status_code, 400)
        self.assertEqual(agent.post(f"/api/v1/support/complaints/{cid}/escalate/", {"reason": "Possible food safety issue"}, format="json").status_code, 200)
        self.assertTrue(Notification.objects.filter(recipient=self.supervisor, kind="COMPLAINT_ESCALATED").exists())
        self.assertEqual(agent.post(f"/api/v1/support/complaints/{cid}/resolve/", {"resolution": "done"}, format="json").status_code, 403)
        customer_view = self.as_(self.customer_user).get(f"/api/v1/support/complaints/{cid}/").json()
        self.assertNotIn("escalation_reason", customer_view)
        self.assertNotIn("ESCALATED", [e["kind"] for e in customer_view["timeline"]])
        self.assertEqual(supervisor.post(f"/api/v1/support/complaints/{cid}/take-over/").status_code, 200)
        self.assertEqual(Complaint.objects.get().assigned_to, self.supervisor)
        self.assertEqual(supervisor.post(f"/api/v1/support/complaints/{cid}/resolve/", {"resolution": "Store warned and refund issued"}, format="json").status_code, 200)

    def test_only_supervisors_reject_and_agent_cannot_take_over(self):
        cid = self.complaint()["id"]
        agent = self.as_(self.agent)
        agent.post(f"/api/v1/support/complaints/{cid}/assign/", {}, format="json")
        self.assertEqual(agent.post(f"/api/v1/support/complaints/{cid}/reject/", {"reason": "spam"}, format="json").status_code, 403)
        self.assertEqual(agent.post(f"/api/v1/support/complaints/{cid}/take-over/").status_code, 403)
        sup = self.as_(self.supervisor)
        self.assertEqual(sup.post(f"/api/v1/support/complaints/{cid}/reject/", {"reason": ""}, format="json").status_code, 400)
        self.assertEqual(sup.post(f"/api/v1/support/complaints/{cid}/reject/", {"reason": "Not supported by order records"}, format="json").status_code, 200)
        self.assertTrue(AuditEvent.objects.filter(action="complaint.reject").exists())

    def test_agent_cannot_touch_another_agents_complaint(self):
        cid = self.complaint()["id"]
        self.as_(self.agent).post(f"/api/v1/support/complaints/{cid}/assign/", {}, format="json")
        rival = self.as_(self.agent2)
        self.assertEqual(rival.get(f"/api/v1/support/complaints/{cid}/").status_code, 404)
        self.assertEqual(rival.post(f"/api/v1/support/complaints/{cid}/resolve/", {"resolution": "x"}, format="json").status_code, 404)

    def test_complainant_withdraws_and_reopens_within_window_only(self):
        cid = self.complaint()["id"]
        customer = self.as_(self.customer_user)
        agent = self.as_(self.agent)
        agent.post(f"/api/v1/support/complaints/{cid}/assign/", {}, format="json")
        agent.post(f"/api/v1/support/complaints/{cid}/resolve/", {"resolution": "Refund sent"}, format="json")
        self.assertEqual(customer.post(f"/api/v1/support/complaints/{cid}/reopen/", {"reason": "Refund never arrived"}, format="json").status_code, 200)
        self.assertEqual(Complaint.objects.get().status, ComplaintStatus.UNDER_REVIEW)
        agent.post(f"/api/v1/support/complaints/{cid}/resolve/", {"resolution": "Refund resent"}, format="json")
        Complaint.objects.update(resolved_at=timezone.now() - timedelta(days=30))
        late = customer.post(f"/api/v1/support/complaints/{cid}/reopen/", {"reason": "Still wrong"}, format="json")
        self.assertEqual(late.status_code, 400)
        self.assertEqual(self.as_(self.supervisor).post(f"/api/v1/support/complaints/{cid}/reopen/", {"reason": "Supervisor review"}, format="json").status_code, 200)

    def test_other_customers_and_non_staff_cannot_run_staff_actions(self):
        cid = self.complaint()["id"]
        for user in (self.customer_user, self.other_customer("nope"), self.store_user):
            api = self.as_(user)
            self.assertIn(api.post(f"/api/v1/support/complaints/{cid}/assign/", {}, format="json").status_code, (403, 404))
            self.assertIn(api.post(f"/api/v1/support/complaints/{cid}/resolve/", {"resolution": "x"}, format="json").status_code, (403, 404))

    def test_complaint_attachment_visibility(self):
        cid = self.complaint(**{})["id"]
        customer = self.as_(self.customer_user)
        customer.post(f"/api/v1/support/complaints/{cid}/comments/", {"body": "evidence", "attachments": [jpeg()]}, format="multipart")
        attachment = Complaint.objects.get().attachments.get()
        url = f"/api/v1/support/attachments/complaint/{attachment.pk}/file/"
        self.assertEqual(customer.get(url).status_code, 200)
        self.assertEqual(self.as_(self.supervisor).get(url).status_code, 200)
        self.assertEqual(self.as_(self.store_user).get(url).status_code, 404)
        self.assertEqual(self.as_(self.other_customer("peeker")).get(url).status_code, 404)

    def test_complaint_sla_breach_reminder(self):
        self.complaint()
        Complaint.objects.update(acknowledge_due=timezone.now() - timedelta(hours=1))
        self.assertGreaterEqual(services.send_sla_reminders()["breached"], 1)
        self.assertTrue(Notification.objects.filter(recipient=self.supervisor, title__contains="SLA breached").exists())

    def test_summary_counts(self):
        self.complaint()
        self.ticket()
        data = self.as_(self.supervisor).get("/api/v1/support/summary/").json()
        self.assertEqual(data["complaints"]["unassigned"], 1)
        self.assertEqual(data["tickets"]["unassigned"], 1)


class FeedbackTests(SupportBase):
    def submit(self, **extra):
        data = {"kind": "SUGGESTION", "subject_type": "PLATFORM", "message": "Please add dark mode", **extra}
        return self.as_(self.customer_user).post("/api/v1/feedback/", data, format="json")

    def test_submit_reply_and_privacy(self):
        response = self.submit()
        self.assertEqual(response.status_code, 201, response.content)
        fid = response.json()["id"]
        agent = self.as_(self.agent)
        agent.post(f"/api/v1/feedback/{fid}/replies/", {"body": "Duplicate of #12", "is_internal": True}, format="json")
        agent.post(f"/api/v1/feedback/{fid}/replies/", {"body": "Thanks, we are considering it"}, format="json")
        mine = self.as_(self.customer_user).get(f"/api/v1/feedback/{fid}/").json()
        self.assertEqual([r["body"] for r in mine["replies"]], ["Thanks, we are considering it"])
        self.assertEqual(mine["status"], "REPLIED")
        self.assertNotIn("ticket", mine)
        self.assertEqual(self.as_(self.other_customer("fb-other")).get(f"/api/v1/feedback/{fid}/").status_code, 404)
        self.assertTrue(Notification.objects.filter(recipient=self.customer_user, kind="FEEDBACK_REPLY").exists())

    def test_customer_cannot_use_staff_actions(self):
        fid = self.submit().json()["id"]
        api = self.as_(self.customer_user)
        self.assertEqual(api.post(f"/api/v1/feedback/{fid}/status/", {"status": "CLOSED"}, format="json").status_code, 403)
        self.assertEqual(api.post(f"/api/v1/feedback/{fid}/escalate/").status_code, 403)
        self.assertEqual(api.post(f"/api/v1/feedback/{fid}/replies/", {"body": "x", "is_internal": True}, format="json").status_code, 403)

    def test_escalation_creates_ticket_for_author_once(self):
        fid = self.submit(kind="ISSUE", message="The app keeps crashing on checkout").json()["id"]
        agent = self.as_(self.agent)
        response = agent.post(f"/api/v1/feedback/{fid}/escalate/")
        self.assertEqual(response.status_code, 200, response.content)
        ticket = Ticket.objects.get()
        self.assertEqual((ticket.requester, ticket.assigned_to), (self.customer_user, self.agent))
        self.assertEqual(response.json()["status"], "ESCALATED")
        self.assertEqual(agent.post(f"/api/v1/feedback/{fid}/escalate/").status_code, 400)
        self.assertEqual(self.as_(self.customer_user).get(f"/api/v1/support/tickets/{ticket.pk}/").status_code, 200)

    def test_store_feedback_visible_to_that_store_only(self):
        fid = self.submit(subject_type="STORE", store=self.store.pk, message="Great packaging!").json()["id"]
        self.assertEqual(self.as_(self.store_user).get("/api/v1/feedback/").json()["count"], 1)
        rival = self.create_store_user(store=self.create_store(name="Feedback Rival"), username="fb-rival")
        self.assertEqual(self.as_(rival).get("/api/v1/feedback/").json()["count"], 0)
        self.assertEqual(self.as_(rival).get(f"/api/v1/feedback/{fid}/").status_code, 404)
        seen = self.as_(self.store_user).get(f"/api/v1/feedback/{fid}/").json()
        self.assertEqual(seen["author_name"], "Delivery C.")  # store sees a short name, not full identity

    def test_validation(self):
        self.assertEqual(self.submit(message="x").status_code, 400)
        self.assertEqual(self.submit(subject_type="STORE").status_code, 400)
        self.assertEqual(self.submit(kind="BOGUS").status_code, 400)
        self.assertEqual(self.submit(order=999999).status_code, 400)
