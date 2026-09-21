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

