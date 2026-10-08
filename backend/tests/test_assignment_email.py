from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch
from bson import ObjectId
from starlette.background import BackgroundTasks

import email_utils
from email_utils import (
    send_assignment_email,
    send_task_assignment_email,
    send_opportunity_assignment_email,
    notify_assignment_by_email,
)
from hub_utils import find_user


@pytest.fixture(autouse=True)
def _email_configured(monkeypatch):
    # email_utils skips sending when Brevo isn't configured; these tests mock the HTTP call.
    monkeypatch.setenv("BREVO_API_KEY", "test-key")
    monkeypatch.setenv("BREVO_SENDER_EMAIL", "noreply@test.wavygo.in")


def test_send_task_assignment_email_payload():
    with patch("email_utils.requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_post.return_value = mock_response

        success = send_task_assignment_email(
            recipient_email="employee@wavygo.in",
            recipient_name="John Doe",
            task_title="Deploy Fleet Telematics Service",
            assigned_by="Anil Anand",
            assigned_by_role="Founder",
            priority="high",
            due_date="2026-04-01",
            task_id="task123",
        )

        assert success is True
        assert mock_post.called
        call_args = mock_post.call_args
        data = call_args.kwargs["json"]

        # Verify subject
        assert data["subject"] == "New Task Assigned – Please Check ERP"

        # Verify recipient
        assert data["to"] == [{"email": "employee@wavygo.in", "name": "John Doe"}]

        # Verify suggested text content requirements
        text_content = data["textContent"]
        assert "Hello John Doe," in text_content
        assert "A new task/opportunity has been assigned to you on the ERP. Please log in to the ERP and check the details." in text_content
        assert "Deploy Fleet Telematics Service" in text_content
        assert "Anil Anand" in text_content
        assert "Regards,\nERP Team" in text_content
        assert "/task-board" in text_content

        # Verify HTML content contains key items and ERP direct button
        html_content = data["htmlContent"]
        assert "Deploy Fleet Telematics Service" in html_content
        assert "Anil Anand" in html_content
        assert "Open ERP &amp; Check Details" in html_content or "Open ERP & Check Details" in html_content
        assert "ERP Team" in html_content


def test_send_opportunity_assignment_email_payload():
    with patch("email_utils.requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_post.return_value = mock_response

        success = send_opportunity_assignment_email(
            recipient_email="employee@wavygo.in",
            recipient_name="Jane Smith",
            opp_title="Bihar Tourism EV Partnership",
            assigned_by="Anil Anand",
            assigned_by_role="Founder",
            opp_type="Partnership",
            deadline="2026-05-15",
            opp_id="opp456",
        )

        assert success is True
        assert mock_post.called
        data = mock_post.call_args.kwargs["json"]

        # Verify subject
        assert data["subject"] == "New Opportunity Assigned – Please Check ERP"
        assert data["to"] == [{"email": "employee@wavygo.in", "name": "Jane Smith"}]

        text_content = data["textContent"]
        assert "Hello Jane Smith," in text_content
        assert "A new task/opportunity has been assigned to you on the ERP. Please log in to the ERP and check the details." in text_content
        assert "Bihar Tourism EV Partnership" in text_content
        assert "Anil Anand" in text_content
        assert "Regards,\nERP Team" in text_content
        assert "/opportunity-hub" in text_content


import asyncio


def test_notify_assignment_by_email_with_db():
    async def _test():
        fake_user_id = str(ObjectId())
        registered_email = "assigned.employee@wavygo.in"
        registered_name = "Assigned Employee"

        mock_db = MagicMock()
        mock_user = {
            "_id": ObjectId(fake_user_id),
            "name": registered_name,
            "email": registered_email,
            "role": "Employee",
        }

        with patch("hub_utils.find_user", return_value=mock_user), \
             patch("email_utils.find_user", return_value=mock_user), \
             patch("email_utils.send_assignment_email", return_value=True) as mock_send:

            result = await notify_assignment_by_email(
                db=mock_db,
                assignee_id=fake_user_id,
                item_type="task",
                item_title="Review Q1 EV Battery Metrics",
                assigned_by_name="Anil Anand",
                assigned_by_role="Founder",
                priority="urgent",
                deadline="2026-03-31",
                item_id="task789",
            )

            assert result is True
            mock_send.assert_called_once_with(
                recipient_email=registered_email,
                recipient_name=registered_name,
                item_type="task",
                item_title="Review Q1 EV Battery Metrics",
                assigned_by="Anil Anand",
                assigned_by_role="Founder",
                priority="urgent",
                deadline="2026-03-31",
                item_id="task789",
            )

    asyncio.run(_test())


def test_notify_assignment_by_email_with_background_tasks():
    async def _test():
        fake_user_id = str(ObjectId())
        registered_email = "assigned.employee@wavygo.in"
        registered_name = "Assigned Employee"

        mock_db = MagicMock()
        mock_user = {
            "_id": ObjectId(fake_user_id),
            "name": registered_name,
            "email": registered_email,
            "role": "Employee",
        }

        bg = BackgroundTasks()

        with patch("hub_utils.find_user", return_value=mock_user), \
             patch("email_utils.find_user", return_value=mock_user), \
             patch("email_utils.send_assignment_email", return_value=True) as mock_send:

            result = await notify_assignment_by_email(
                db=mock_db,
                assignee_id=fake_user_id,
                item_type="opportunity",
                item_title="Clean Energy Grant 2026",
                assigned_by_name="Operations Manager",
                assigned_by_role="Manager",
                priority="Grant",
                deadline="2026-06-30",
                item_id="opp999",
                background_tasks=bg,
            )

            assert result is True
            assert len(bg.tasks) == 1
            await bg()
            mock_send.assert_called_once_with(
                recipient_email=registered_email,
                recipient_name=registered_name,
                item_type="opportunity",
                item_title="Clean Energy Grant 2026",
                assigned_by="Operations Manager",
                assigned_by_role="Manager",
                priority="Grant",
                deadline="2026-06-30",
                item_id="opp999",
            )

    asyncio.run(_test())


def test_notify_assignment_by_email_missing_user():
    async def _test():
        mock_db = MagicMock()
        with patch("hub_utils.find_user", return_value=None), \
             patch("email_utils.find_user", return_value=None):
            result = await notify_assignment_by_email(
                db=mock_db,
                assignee_id="nonexistent_id",
                item_type="task",
                item_title="Missing User Task",
                assigned_by_name="Founder",
            )
            assert result is False

    asyncio.run(_test())


def test_notify_assignment_by_email_missing_email():
    async def _test():
        mock_db = MagicMock()
        mock_user = {"_id": ObjectId(), "name": "No Email User", "email": ""}
        with patch("hub_utils.find_user", return_value=mock_user), \
             patch("email_utils.find_user", return_value=mock_user):
            result = await notify_assignment_by_email(
                db=mock_db,
                assignee_id="user_without_email",
                item_type="task",
                item_title="No Email Task",
                assigned_by_name="Founder",
            )
            assert result is False

    asyncio.run(_test())


from unittest.mock import MagicMock, AsyncMock, patch


def test_task_router_create_and_update_dispatches_email():
    from routers.tasks_router import create_task, update_task
    from models_part2 import TaskIn
    from models import UserPublic

    async def _test():
        founder = UserPublic(
            id=str(ObjectId()),
            email="founder@wavygo.in",
            name="Anil Anand",
            role="Founder",
        )
        emp_id = str(ObjectId())

        mock_db = MagicMock()
        mock_insert_res = MagicMock()
        mock_insert_res.inserted_id = ObjectId()

        mock_db.tasks.insert_one = AsyncMock(return_value=mock_insert_res)
        mock_db.activity_logs.insert_one = AsyncMock()
        mock_db.notifications.insert_one = AsyncMock()
        # Assignees are looked up to make sure they are active users.
        mock_db.users.find_one = AsyncMock(return_value={"_id": ObjectId(), "status": "active"})

        # Test create_task
        task_payload = TaskIn(
            title="Integrate GPS Tracker",
            description="Setup tracker",
            status="todo",
            priority="high",
            assignee_id=emp_id,
            module="Fleet",
        )

        bg = BackgroundTasks()

        with patch("routers.tasks_router.get_db", return_value=mock_db), \
             patch("routers.tasks_router.notify_assignment_by_email", new_callable=AsyncMock) as mock_notify_email, \
             patch("routers.tasks_router._enrich_names", new_callable=AsyncMock):

            await create_task(payload=task_payload, background_tasks=bg, current=founder)

            mock_notify_email.assert_called_once()
            call_kwargs = mock_notify_email.call_args.kwargs
            assert call_kwargs["assignee_id"] == emp_id
            assert call_kwargs["item_type"] == "task"
            assert call_kwargs["item_title"] == "Integrate GPS Tracker"
            assert call_kwargs["assigned_by_name"] == "Anil Anand"
            assert call_kwargs["assigned_by_role"] == "Founder"
            assert call_kwargs["priority"] == "high"

        # Test update_task with reassignment
        existing_task = {
            "_id": ObjectId(),
            "title": "Existing Task",
            "assignee_id": str(ObjectId()),
            "status": "todo",
        }
        new_assignee_id = str(ObjectId())

        mock_db.tasks.find_one = AsyncMock(return_value=existing_task)
        mock_update_res = MagicMock()
        mock_update_res.matched_count = 1
        mock_db.tasks.update_one = AsyncMock(return_value=mock_update_res)

        with patch("routers.tasks_router.get_db", return_value=mock_db), \
             patch("routers.tasks_router.notify_assignment_by_email", new_callable=AsyncMock) as mock_notify_email, \
             patch("routers.tasks_router._enrich_names", new_callable=AsyncMock):

            await update_task(
                task_id=str(existing_task["_id"]),
                payload={"assignee_id": new_assignee_id},
                background_tasks=bg,
                current=founder,
            )

            mock_notify_email.assert_called_once()
            call_kwargs = mock_notify_email.call_args.kwargs
            assert call_kwargs["assignee_id"] == new_assignee_id
            assert call_kwargs["item_type"] == "task"

    asyncio.run(_test())


def test_opp_router_create_and_assign_dispatches_email():
    from routers.opportunities_router import create_opp, assign_opp, update_opp
    from models_part2 import OpportunityIn, OpportunityAssign
    from models import UserPublic

    async def _test():
        founder = UserPublic(
            id=str(ObjectId()),
            email="founder@wavygo.in",
            name="Anil Anand",
            role="Founder",
        )
        emp_id = str(ObjectId())

        mock_db = MagicMock()
        mock_insert_res = MagicMock()
        mock_insert_res.inserted_id = ObjectId()

        mock_db.opportunities.insert_one = AsyncMock(return_value=mock_insert_res)
        mock_db.activity_logs.insert_one = AsyncMock()
        mock_db.notifications.insert_one = AsyncMock()
        # assign_opp now checks the assignee exists.
        mock_db.users.find_one = AsyncMock(return_value={"_id": ObjectId(emp_id), "name": "Employee"})

        opp_payload = OpportunityIn(
            title="Patna Junction EV Tender",
            type="Tender",
            description="Gov tender",
            organisation="IRCTC",
            deadline="2026-07-31",
            value_lakhs=45.0,
            status="open",
            assignee_id=emp_id,
        )

        bg = BackgroundTasks()

        # Test create_opp
        with patch("routers.opportunities_router.get_db", return_value=mock_db), \
             patch("routers.opportunities_router.notify_assignment_by_email", new_callable=AsyncMock) as mock_notify_email, \
             patch("routers.opportunities_router._enrich", new_callable=AsyncMock):

            await create_opp(payload=opp_payload, background_tasks=bg, current=founder)

            mock_notify_email.assert_called_once()
            call_kwargs = mock_notify_email.call_args.kwargs
            assert call_kwargs["assignee_id"] == emp_id
            assert call_kwargs["item_type"] == "opportunity"
            assert call_kwargs["item_title"] == "Patna Junction EV Tender"
            assert call_kwargs["assigned_by_name"] == "Anil Anand"
            assert call_kwargs["assigned_by_role"] == "Founder"

        # Test assign_opp
        opp_id = str(ObjectId())
        existing_opp = {
            "_id": ObjectId(opp_id),
            "title": "Bihar Tourism Pilot",
            "type": "Partnership",
            "deadline": "2026-05-20",
            "assignee_id": None,
            "status": "open",
        }

        mock_db.opportunities.find_one = AsyncMock(return_value=existing_opp)
        mock_db.opportunities.update_one = AsyncMock()

        with patch("routers.opportunities_router.get_db", return_value=mock_db), \
             patch("routers.opportunities_router.notify_assignment_by_email", new_callable=AsyncMock) as mock_notify_email, \
             patch("routers.opportunities_router._enrich", new_callable=AsyncMock):

            await assign_opp(
                opp_id=opp_id,
                payload=OpportunityAssign(assignee_id=emp_id),
                background_tasks=bg,
                current=founder,
            )

            mock_notify_email.assert_called_once()
            call_kwargs = mock_notify_email.call_args.kwargs
            assert call_kwargs["assignee_id"] == emp_id
            assert call_kwargs["item_type"] == "opportunity"
            assert call_kwargs["item_title"] == "Bihar Tourism Pilot"

    asyncio.run(_test())



# ------------------------- escaping -------------------------

def _sent_payload(send, **kwargs):
    with patch("email_utils.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=201)
        assert send(**kwargs) is True
        return mock_post.call_args.kwargs["json"]


def test_assignment_email_escapes_user_supplied_html():
    data = _sent_payload(
        send_task_assignment_email,
        recipient_email="employee@wavygo.in",
        recipient_name="<b>Eve</b>",
        task_title='Pay invoice <a href="https://evil.example">here</a>',
        assigned_by="Mallory <script>",
        task_id="t1",
    )
    body = data["htmlContent"]
    assert "evil.example\">here</a>" not in body
    assert "&lt;a href=&quot;https://evil.example&quot;&gt;here&lt;/a&gt;" in body
    assert "<script>" not in body and "<b>Eve</b>" not in body


def test_invitation_and_password_emails_escape_names():
    inv = _sent_payload(email_utils.send_invitation_email, recipient_email="a@wavygo.in",
                        recipient_name="<img src=x>", role="Employee", token="tok",
                        invited_by="<i>Boss</i>", department="<u>Ops</u>")
    assert "<img src=x>" not in inv["htmlContent"] and "&lt;img src=x&gt;" in inv["htmlContent"]
    assert "<i>Boss</i>" not in inv["htmlContent"] and "<u>Ops</u>" not in inv["htmlContent"]
    pwd = _sent_payload(email_utils.send_password_reset_email, recipient_email="a@wavygo.in",
                        recipient_name="A", new_password="p<ss>&1", reset_by="<b>Admin</b>")
    assert "p&lt;ss&gt;&amp;1" in pwd["htmlContent"] and "<b>Admin</b>" not in pwd["htmlContent"]


# ------------------------- calendar -------------------------

@pytest.mark.parametrize("kind", ["invite", "reminder", "rescheduled", "cancelled"])
def test_calendar_email_payload(kind):
    data = _sent_payload(
        email_utils.send_calendar_email,
        recipient_email="ashish@wavygo.in", recipient_name="Ashish", kind=kind,
        title="Design <review>", when="Mon 28 Sep 2026, 07:45 AM – 08:45 AM IST",
        actor="Anil Anand", location="Conf room", meeting_link="https://meet.google.com/abc",
        event_id="ev1", when_phrase="starts in 15 min",
    )
    assert data["to"] == [{"email": "ashish@wavygo.in", "name": "Ashish"}]
    assert "Design <review>" in data["subject"]
    assert "Design &lt;review&gt;" in data["htmlContent"]
    assert "/calendar?event=ev1" in data["htmlContent"]
    assert ("meet.google.com" in data["htmlContent"]) == (kind != "cancelled")


def test_calendar_email_rejects_unsafe_meeting_link_and_unknown_kind():
    data = _sent_payload(
        email_utils.send_calendar_email, recipient_email="a@wavygo.in", recipient_name="A", kind="invite",
        title="T", when="now", meeting_link="javascript:alert(1)",
    )
    assert "javascript:" not in data["htmlContent"]
    with pytest.raises(ValueError):
        email_utils.send_calendar_email(recipient_email="a@wavygo.in", recipient_name="A", kind="nope", title="T", when="x")


def test_calendar_email_skipped_when_unconfigured(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "")
    with patch("email_utils.requests.post") as mock_post:
        assert email_utils.send_calendar_email(recipient_email="a@wavygo.in", recipient_name="A",
                                               kind="invite", title="T", when="x") is False
        assert not mock_post.called
