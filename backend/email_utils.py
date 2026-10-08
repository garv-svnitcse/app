from __future__ import annotations
import html
import logging
import os
import requests
from urllib.parse import quote
from hub_utils import find_user

logger = logging.getLogger(__name__)

# Brevo credentials come from the environment only (BREVO_API_KEY, BREVO_SENDER_EMAIL,
# optional BREVO_SENDER_NAME). Without them every sender is a logged no-op.
BREVO_URL = "https://api.brevo.com/v3/smtp/email"
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://app-eta-flax-97.vercel.app")


def _brevo_key() -> str:
    return (os.environ.get("BREVO_API_KEY") or "").strip()


def _sender() -> dict:
    email = (os.environ.get("BREVO_SENDER_EMAIL") or "").strip()
    name = (os.environ.get("BREVO_SENDER_NAME") or "WavyGo OS").strip()
    return {"name": name, "email": email}


def email_configured() -> bool:
    """True when both an API key and a sender address are configured."""
    return bool(_brevo_key() and _sender()["email"])


def _esc(value) -> str:
    """HTML-escape a value for an email body (None becomes empty)."""
    return html.escape("" if value is None else str(value), quote=True)


def _skip_unconfigured(kind: str, recipient: str) -> bool:
    """Log and report True when sending must be skipped because email is not configured."""
    if email_configured():
        return False
    logger.warning("[Email] BREVO_API_KEY / BREVO_SENDER_EMAIL not configured; skipped %s email to %s", kind, recipient)
    return True


def send_invitation_email(
    recipient_email: str,
    recipient_name: str,
    role: str,
    token: str,
    invited_by: str,
    designation: str | None = None,
    department: str | None = None,
) -> bool:
    """Send team invitation email via Brevo REST API."""
    if _skip_unconfigured("invitation", recipient_email):
        return False

    accept_url = f"{FRONTEND_URL}/accept-invite?token={quote(token)}"
    url = BREVO_URL
    # Names, roles and the inviter come from user input; escape them so they render as text.
    h_name, h_role, h_by, h_url = _esc(recipient_name), _esc(role), _esc(invited_by), _esc(accept_url)
    headers = {
        "api-key": _brevo_key(),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Mailin-Track": "0",
        "X-Mailin-Click": "0"
    }

    desig_html = f"<div><strong>Designation:</strong> {_esc(designation)}</div>" if designation else ""
    dept_html = f"<div><strong>Department:</strong> {_esc(department)}</div>" if department else ""

    text_content = f"Hello {recipient_name},\n\nYou have been invited by {invited_by} to join WavyGo OS as {role}.\n\nPlease click the link below to accept your invitation:\n{accept_url}\n\n© 2026 WavyGo OS"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b; }}
    .card {{ max-width: 540px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 36px; box-shadow: 0 4px 16px rgba(0,0,0,0.06); border: 1px solid #e2e8f0; }}
    .brand {{ text-align: center; margin-bottom: 24px; }}
    .brand-name {{ font-size: 26px; font-weight: 800; color: #2563eb; letter-spacing: -0.5px; margin: 0; }}
    .badge {{ display: inline-block; background: #eff6ff; color: #1d4ed8; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; text-transform: uppercase; margin-top: 6px; }}
    .greeting {{ font-size: 18px; font-weight: 600; color: #0f172a; margin-top: 0; }}
    .text {{ font-size: 15px; line-height: 1.6; color: #475569; }}
    .box {{ background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 16px; margin: 20px 0; font-size: 14px; line-height: 1.6; }}
    .btn-wrapper {{ text-align: center; margin: 32px 0 24px 0; }}
    .btn {{ background-color: #2563eb; color: #ffffff !important; font-size: 15px; font-weight: 600; text-decoration: none; padding: 14px 32px; border-radius: 8px; display: inline-block; }}
    .link-note {{ font-size: 13px; color: #64748b; text-align: center; word-break: break-all; }}
    .footer {{ text-align: center; font-size: 12px; color: #94a3b8; margin-top: 32px; border-top: 1px solid #f1f5f9; padding-top: 20px; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="brand">
      <h1 class="brand-name">WavyGo OS</h1>
      <span class="badge">Team Invitation</span>
    </div>
    <p class="greeting">Hello {h_name},</p>
    <p class="text">You have been invited by <strong>{h_by}</strong> to join the <strong>WavyGo OS</strong> workspace.</p>
    
    <div class="box">
      <div><strong>Role:</strong> {h_role}</div>
      {desig_html}
      {dept_html}
    </div>

    <p class="text">Please click the button below to accept your invitation and set up your account password. Once accepted, your profile will be added to the employee directory.</p>

    <div class="btn-wrapper">
      <a href="{h_url}" class="btn" target="_blank">Accept Invitation &amp; Join Team</a>
    </div>

    <div class="link-note">
      If the button does not work, copy and paste this URL into your browser:<br>
      <a href="{h_url}" style="color: #2563eb;">{h_url}</a>
    </div>

    <div class="footer">
      <p>© 2026 WavyGo OS · Enterprise Workspace Platform</p>
    </div>
  </div>
</body>
</html>"""

    data = {
        "sender": _sender(),
        "to": [{"email": recipient_email, "name": recipient_name}],
        "subject": f"You're invited to join WavyGo OS as {role}",
        "htmlContent": html_content,
        "textContent": text_content
    }

    try:
        response = requests.post(url, json=data, headers=headers, timeout=15, allow_redirects=True)
        if response.status_code in (200, 201, 202):
            logger.info(f"[Email] Invitation email sent to {recipient_email}")
            return True
        else:
            logger.error(f"[Email] Failed to send email to {recipient_email}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"[Email] Exception sending email: {e}")
        return False


def send_password_reset_email(
    recipient_email: str,
    recipient_name: str,
    new_password: str,
    reset_by: str,
) -> bool:
    """Send password reset notification email with new password via Brevo REST API."""
    if _skip_unconfigured("password reset", recipient_email):
        return False

    login_url = f"{FRONTEND_URL}/login"
    url = BREVO_URL
    h_name, h_by, h_email, h_pwd = _esc(recipient_name), _esc(reset_by), _esc(recipient_email), _esc(new_password)
    headers = {
        "api-key": _brevo_key(),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Mailin-Track": "0",
        "X-Mailin-Click": "0"
    }

    text_content = (
        f"Hello {recipient_name},\n\n"
        f"Your account password for WavyGo OS has been updated by {reset_by}.\n\n"
        f"Your Updated Login Credentials:\n"
        f"Email: {recipient_email}\n"
        f"New Password: {new_password}\n\n"
        f"Please log in using your new password at:\n{login_url}\n\n"
        f"If you did not expect this change, please contact your workspace administrator immediately.\n\n"
        f"© 2026 WavyGo OS"
    )

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b; }}
    .card {{ max-width: 540px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 36px; box-shadow: 0 4px 16px rgba(0,0,0,0.06); border: 1px solid #e2e8f0; }}
    .brand {{ text-align: center; margin-bottom: 24px; }}
    .brand-name {{ font-size: 26px; font-weight: 800; color: #2563eb; letter-spacing: -0.5px; margin: 0; }}
    .badge {{ display: inline-block; background: #fef3c7; color: #b45309; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; text-transform: uppercase; margin-top: 6px; }}
    .greeting {{ font-size: 18px; font-weight: 600; color: #0f172a; margin-top: 0; }}
    .text {{ font-size: 15px; line-height: 1.6; color: #475569; }}
    .cred-box {{ background: #0f172a; border-radius: 8px; padding: 20px; margin: 20px 0; border: 1px solid #1e293b; }}
    .cred-row {{ margin-bottom: 14px; }}
    .cred-row:last-child {{ margin-bottom: 0; }}
    .cred-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: #94a3b8; font-weight: 600; margin-bottom: 4px; }}
    .cred-email {{ font-family: 'Courier New', Courier, monospace; font-size: 15px; font-weight: 600; color: #38bdf8; word-break: break-all; }}
    .cred-pwd {{ font-family: 'Courier New', Courier, monospace; font-size: 18px; font-weight: 700; color: #fbbf24; word-break: break-all; letter-spacing: 1px; }}
    .btn-wrapper {{ text-align: center; margin: 30px 0 24px 0; }}
    .btn {{ background-color: #2563eb; color: #ffffff !important; font-size: 15px; font-weight: 600; text-decoration: none; padding: 14px 32px; border-radius: 8px; display: inline-block; }}
    .security-note {{ font-size: 13px; color: #64748b; background: #f8fafc; border-left: 4px solid #f59e0b; padding: 12px 16px; border-radius: 4px; margin-top: 20px; line-height: 1.5; }}
    .footer {{ text-align: center; font-size: 12px; color: #94a3b8; margin-top: 32px; border-top: 1px solid #f1f5f9; padding-top: 20px; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="brand">
      <h1 class="brand-name">WavyGo OS</h1>
      <span class="badge">Password Reset</span>
    </div>
    <p class="greeting">Hello {h_name},</p>
    <p class="text">Your account password for <strong>WavyGo OS</strong> has been reset by <strong>{h_by}</strong>.</p>
    
    <div class="cred-box">
      <div class="cred-row">
        <div class="cred-label">Account Email</div>
        <div class="cred-email">{h_email}</div>
      </div>
      <div class="cred-row">
        <div class="cred-label">New Password</div>
        <div class="cred-pwd">{h_pwd}</div>
      </div>
    </div>

    <p class="text">You can now sign in using your updated password. Click the button below to access your workspace:</p>

    <div class="btn-wrapper">
      <a href="{login_url}" class="btn" target="_blank">Sign In to WavyGo OS</a>
    </div>

    <div class="security-note">
      <strong>Security Notice:</strong> For security, we recommend changing your password after logging in if permitted. Never share your credentials with anyone. If you did not expect this reset, contact your administrator immediately.
    </div>

    <div class="footer">
      <p>© 2026 WavyGo OS · Enterprise Workspace Platform</p>
    </div>
  </div>
</body>
</html>"""

    data = {
        "sender": _sender(),
        "to": [{"email": recipient_email, "name": recipient_name}],
        "subject": "Your WavyGo OS Password Has Been Reset",
        "htmlContent": html_content,
        "textContent": text_content
    }

    try:
        response = requests.post(url, json=data, headers=headers, timeout=15, allow_redirects=True)
        if response.status_code in (200, 201, 202):
            logger.info(f"[Email] Password reset email sent to {recipient_email}")
            return True
        else:
            logger.error(f"[Email] Failed to send password reset email to {recipient_email}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"[Email] Exception sending password reset email: {e}")
        return False


def send_assignment_email(
    recipient_email: str,
    recipient_name: str,
    item_type: str = "task",
    item_title: str = "",
    assigned_by: str = "",
    assigned_by_role: str | None = None,
    priority: str | None = None,
    deadline: str | None = None,
    item_id: str | None = None,
    subject: str | None = None,
    erp_url: str | None = None,
) -> bool:
    """Send automatic email notification to assigned employee when task/opportunity is assigned."""
    if _skip_unconfigured("assignment", recipient_email):
        return False

    is_task = item_type.lower() == "task"
    if not subject:
        subject = "New Task Assigned – Please Check ERP" if is_task else "New Opportunity Assigned – Please Check ERP"

    if not erp_url:
        if is_task:
            # TaskBoard opens ?task_id=<id> directly; the Opportunity Hub opens ?opp=<id>
            erp_url = f"{FRONTEND_URL}/task-board" + (f"?task_id={quote(str(item_id))}" if item_id else "")
        else:
            erp_url = f"{FRONTEND_URL}/opportunity-hub" + (f"?opp={quote(str(item_id))}" if item_id else "")

    url = BREVO_URL
    headers = {
        "api-key": _brevo_key(),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Mailin-Track": "0",
        "X-Mailin-Click": "0"
    }

    role_info = f" ({assigned_by_role})" if assigned_by_role else ""
    h_name, h_title, h_by, h_url = _esc(recipient_name), _esc(item_title), _esc(assigned_by), _esc(erp_url)
    h_role_info = _esc(role_info)
    priority_info = f"\nPriority: {priority}" if priority else ""
    deadline_info = f"\nDeadline / Due Date: {deadline}" if deadline else ""

    text_content = (
        f"Hello {recipient_name},\n\n"
        f"A new task/opportunity has been assigned to you on the ERP. Please log in to the ERP and check the details.\n\n"
        f"Details:\n"
        f"- {item_type.capitalize()}: {item_title}\n"
        f"- Assigned by: {assigned_by}{role_info}"
        f"{priority_info}"
        f"{deadline_info}\n\n"
        f"Please open the ERP to view full details:\n{erp_url}\n\n"
        f"Regards,\n"
        f"ERP Team"
    )

    badge_label = "Task Assigned" if is_task else "Opportunity Assigned"
    item_label = "Task Title" if is_task else "Opportunity Title"

    extra_rows = []
    if priority:
        extra_rows.append(f'<div class="item-row"><strong>Priority / Type:</strong> {_esc(priority)}</div>')
    if deadline:
        extra_rows.append(f'<div class="item-row"><strong>Due Date / Deadline:</strong> {_esc(deadline)}</div>')
    extra_html = "\n      ".join(extra_rows)

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b; }}
    .card {{ max-width: 540px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 36px; box-shadow: 0 4px 16px rgba(0,0,0,0.06); border: 1px solid #e2e8f0; }}
    .brand {{ text-align: center; margin-bottom: 24px; }}
    .brand-name {{ font-size: 26px; font-weight: 800; color: #2563eb; letter-spacing: -0.5px; margin: 0; }}
    .badge {{ display: inline-block; background: #eff6ff; color: #1d4ed8; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; text-transform: uppercase; margin-top: 6px; }}
    .greeting {{ font-size: 18px; font-weight: 600; color: #0f172a; margin-top: 0; }}
    .text {{ font-size: 15px; line-height: 1.6; color: #475569; }}
    .item-box {{ background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 18px; margin: 20px 0; font-size: 14px; line-height: 1.6; }}
    .item-row {{ margin-bottom: 8px; }}
    .item-row:last-child {{ margin-bottom: 0; }}
    .btn-wrapper {{ text-align: center; margin: 30px 0 24px 0; }}
    .btn {{ background-color: #2563eb; color: #ffffff !important; font-size: 15px; font-weight: 600; text-decoration: none; padding: 14px 32px; border-radius: 8px; display: inline-block; }}
    .link-note {{ font-size: 13px; color: #64748b; text-align: center; word-break: break-all; }}
    .signoff {{ font-size: 15px; color: #334155; margin-top: 24px; line-height: 1.6; }}
    .footer {{ text-align: center; font-size: 12px; color: #94a3b8; margin-top: 32px; border-top: 1px solid #f1f5f9; padding-top: 20px; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="brand">
      <h1 class="brand-name">WavyGo OS</h1>
      <span class="badge">{badge_label}</span>
    </div>
    <p class="greeting">Hello {h_name},</p>
    <p class="text">A new task/opportunity has been assigned to you on the ERP. Please log in to the ERP and check the details.</p>
    
    <div class="item-box">
      <div class="item-row"><strong>{item_label}:</strong> {h_title}</div>
      <div class="item-row"><strong>Assigned by:</strong> {h_by}{h_role_info}</div>
      {extra_html}
    </div>

    <p class="text">You have been directed to open the ERP to review all assignment details, milestones, and instructions.</p>

    <div class="btn-wrapper">
      <a href="{h_url}" class="btn" target="_blank">Open ERP &amp; Check Details</a>
    </div>

    <div class="link-note">
      If the button does not work, copy and paste this URL into your browser:<br>
      <a href="{h_url}" style="color: #2563eb;">{h_url}</a>
    </div>

    <p class="signoff">
      Regards,<br>
      <strong>ERP Team</strong>
    </p>

    <div class="footer">
      <p>© 2026 WavyGo OS · Enterprise Resource Planning System</p>
    </div>
  </div>
</body>
</html>"""

    data = {
        "sender": _sender(),
        "to": [{"email": recipient_email, "name": recipient_name}],
        "subject": subject,
        "htmlContent": html_content,
        "textContent": text_content
    }

    try:
        response = requests.post(url, json=data, headers=headers, timeout=15, allow_redirects=True)
        if response.status_code in (200, 201, 202):
            logger.info(f"[Email] Assignment email sent to {recipient_email} for {item_type} '{item_title}'")
            return True
        else:
            logger.error(f"[Email] Failed to send assignment email to {recipient_email}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"[Email] Exception sending assignment email: {e}")
        return False


def send_task_assignment_email(
    recipient_email: str,
    recipient_name: str,
    task_title: str,
    assigned_by: str,
    assigned_by_role: str | None = None,
    priority: str | None = None,
    due_date: str | None = None,
    task_id: str | None = None,
) -> bool:
    """Convenience helper to send task assignment notification email."""
    return send_assignment_email(
        recipient_email=recipient_email,
        recipient_name=recipient_name,
        item_type="task",
        item_title=task_title,
        assigned_by=assigned_by,
        assigned_by_role=assigned_by_role,
        priority=priority,
        deadline=due_date,
        item_id=task_id,
        subject="New Task Assigned – Please Check ERP",
    )


def send_opportunity_assignment_email(
    recipient_email: str,
    recipient_name: str,
    opp_title: str,
    assigned_by: str,
    assigned_by_role: str | None = None,
    opp_type: str | None = None,
    deadline: str | None = None,
    opp_id: str | None = None,
) -> bool:
    """Convenience helper to send opportunity assignment notification email."""
    return send_assignment_email(
        recipient_email=recipient_email,
        recipient_name=recipient_name,
        item_type="opportunity",
        item_title=opp_title,
        assigned_by=assigned_by,
        assigned_by_role=assigned_by_role,
        priority=opp_type,
        deadline=deadline,
        item_id=opp_id,
        subject="New Opportunity Assigned – Please Check ERP",
    )


async def notify_assignment_by_email(
    db,
    assignee_id: str | None,
    item_type: str,
    item_title: str,
    assigned_by_name: str,
    assigned_by_role: str | None = None,
    priority: str | None = None,
    deadline: str | None = None,
    item_id: str | None = None,
    background_tasks = None,
) -> bool:
    """Fetch assigned employee's registered email from ERP db and immediately send notification email."""
    if not assignee_id:
        return False

    assignee = await find_user(db, assignee_id)
    if not assignee:
        logger.info(f"[Email] Assignee user '{assignee_id}' not found in ERP directory")
        return False

    recipient_email = (assignee.get("email") or "").strip()
    if not recipient_email:
        logger.info(f"[Email] Assignee user '{assignee_id}' does not have a registered email in ERP")
        return False

    recipient_name = assignee.get("name") or "Employee"

    if background_tasks is not None:
        background_tasks.add_task(
            send_assignment_email,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            item_type=item_type,
            item_title=item_title,
            assigned_by=assigned_by_name,
            assigned_by_role=assigned_by_role,
            priority=priority,
            deadline=deadline,
            item_id=item_id,
        )
    else:
        send_assignment_email(
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            item_type=item_type,
            item_title=item_title,
            assigned_by=assigned_by_name,
            assigned_by_role=assigned_by_role,
            priority=priority,
            deadline=deadline,
            item_id=item_id,
        )
    return True




def send_password_reset_link_email(
    recipient_email: str,
    recipient_name: str,
    reset_url: str,
    expires_minutes: int = 30,
) -> bool:
    """Send a self-service password reset link via Brevo REST API.

    The caller builds `reset_url` (it carries the raw single-use token). Returns
    False, after logging, when email is not configured or sending fails.
    """
    if _skip_unconfigured("password reset link", recipient_email):
        return False

    name = html.escape(recipient_name or "there")
    safe_url = html.escape(reset_url, quote=True)
    headers = {
        "api-key": _brevo_key(),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Mailin-Track": "0",
        "X-Mailin-Click": "0"
    }

    text_content = (
        f"Hello {recipient_name or 'there'},\n\n"
        f"We received a request to reset the password for your WavyGo OS account ({recipient_email}).\n\n"
        f"Open the link below to choose a new password. It can be used once and expires in {expires_minutes} minutes:\n"
        f"{reset_url}\n\n"
        f"If you did not request this, you can ignore this email; your password will not change.\n\n"
        f"© 2026 WavyGo OS"
    )

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b; }}
    .card {{ max-width: 540px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 36px; box-shadow: 0 4px 16px rgba(0,0,0,0.06); border: 1px solid #e2e8f0; }}
    .brand {{ text-align: center; margin-bottom: 24px; }}
    .brand-name {{ font-size: 26px; font-weight: 800; color: #2563eb; letter-spacing: -0.5px; margin: 0; }}
    .badge {{ display: inline-block; background: #fef3c7; color: #b45309; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; text-transform: uppercase; margin-top: 6px; }}
    .greeting {{ font-size: 18px; font-weight: 600; color: #0f172a; margin-top: 0; }}
    .text {{ font-size: 15px; line-height: 1.6; color: #475569; }}
    .btn-wrapper {{ text-align: center; margin: 32px 0 24px 0; }}
    .btn {{ background-color: #2563eb; color: #ffffff !important; font-size: 15px; font-weight: 600; text-decoration: none; padding: 14px 32px; border-radius: 8px; display: inline-block; }}
    .link-note {{ font-size: 13px; color: #64748b; text-align: center; word-break: break-all; }}
    .security-note {{ font-size: 13px; color: #64748b; background: #f8fafc; border-left: 4px solid #f59e0b; padding: 12px 16px; border-radius: 4px; margin-top: 20px; line-height: 1.5; }}
    .footer {{ text-align: center; font-size: 12px; color: #94a3b8; margin-top: 32px; border-top: 1px solid #f1f5f9; padding-top: 20px; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="brand">
      <h1 class="brand-name">WavyGo OS</h1>
      <span class="badge">Password Reset</span>
    </div>
    <p class="greeting">Hello {name},</p>
    <p class="text">We received a request to reset the password for your <strong>WavyGo OS</strong> account. Click the button below to choose a new password.</p>

    <div class="btn-wrapper">
      <a href="{safe_url}" class="btn" target="_blank">Reset My Password</a>
    </div>

    <div class="link-note">
      If the button does not work, copy and paste this URL into your browser:<br>
      <a href="{safe_url}" style="color: #2563eb;">{safe_url}</a>
    </div>

    <div class="security-note">
      <strong>Security Notice:</strong> This link can be used once and expires in {expires_minutes} minutes. If you did not request a password reset, you can safely ignore this email; your password will not change.
    </div>

    <div class="footer">
      <p>© 2026 WavyGo OS · Enterprise Workspace Platform</p>
    </div>
  </div>
</body>
</html>"""

    data = {
        "sender": _sender(),
        "to": [{"email": recipient_email, "name": recipient_name or recipient_email}],
        "subject": "Reset your WavyGo OS password",
        "htmlContent": html_content,
        "textContent": text_content
    }

    try:
        response = requests.post(BREVO_URL, json=data, headers=headers, timeout=15, allow_redirects=True)
        if response.status_code in (200, 201, 202):
            logger.info("[Email] Password reset link sent to %s", recipient_email)
            return True
        logger.error("[Email] Failed to send password reset link to %s: %s - %s",
                     recipient_email, response.status_code, response.text)
        return False
    except Exception as e:
        logger.error("[Email] Exception sending password reset link: %s", e)
        return False


# ------------------------- calendar -------------------------

CALENDAR_EMAILS = {
    # kind: (badge, badge background, badge colour, subject prefix, headline)
    "invite":     ("Event Invitation", "#eff6ff", "#1d4ed8", "Invitation", "{actor} invited you to an event."),
    "reminder":   ("Event Reminder",   "#ecfdf5", "#047857", "Reminder",   "Your event {when_phrase}."),
    "rescheduled": ("Event Rescheduled", "#fef3c7", "#b45309", "Rescheduled", "{actor} moved this event to a new time. Please reply again."),
    "cancelled":  ("Event Cancelled",  "#fef2f2", "#b91c1c", "Cancelled",  "{actor} cancelled this event."),
}


def send_calendar_email(
    recipient_email: str,
    recipient_name: str,
    kind: str,
    title: str,
    when: str,
    actor: str = "",
    location: str | None = None,
    meeting_link: str | None = None,
    event_id: str | None = None,
    when_phrase: str = "starts soon",
) -> bool:
    """Calendar invitation / reminder / reschedule / cancellation email via Brevo."""
    if kind not in CALENDAR_EMAILS:
        raise ValueError(f"unknown calendar email kind: {kind}")
    if _skip_unconfigured(f"calendar {kind}", recipient_email):
        return False

    badge, badge_bg, badge_fg, prefix, headline = CALENDAR_EMAILS[kind]
    headline = headline.format(actor=actor or "Someone", when_phrase=when_phrase)
    event_url = f"{FRONTEND_URL}/calendar" + (f"?event={quote(str(event_id))}" if event_id else "")
    join_url = meeting_link if meeting_link and meeting_link.startswith(("https://", "http://")) else None
    struck = kind == "cancelled"

    rows = [f'<div class="item-row"><strong>When:</strong> {_esc(when)}</div>']
    if location:
        rows.append(f'<div class="item-row"><strong>Where:</strong> {_esc(location)}</div>')
    if join_url and not struck:
        rows.append(f'<div class="item-row"><strong>Online:</strong> <a href="{_esc(join_url)}" style="color:#2563eb;">Join meeting</a></div>')
    rows_html = "\n      ".join(rows)
    title_html = f'<s>{_esc(title)}</s>' if struck else _esc(title)

    text_lines = [
        f"Hello {recipient_name or 'there'},",
        "",
        headline,
        "",
        f"{title}",
        f"When: {when}",
        *( [f"Where: {location}"] if location else [] ),
        *( [f"Join: {join_url}"] if join_url and not struck else [] ),
        "",
        f"Open in WavyGo OS: {event_url}",
        "",
        "© 2026 WavyGo OS",
    ]

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b; }}
    .card {{ max-width: 540px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 36px; box-shadow: 0 4px 16px rgba(0,0,0,0.06); border: 1px solid #e2e8f0; }}
    .brand {{ text-align: center; margin-bottom: 24px; }}
    .brand-name {{ font-size: 26px; font-weight: 800; color: #2563eb; letter-spacing: -0.5px; margin: 0; }}
    .badge {{ display: inline-block; background: {badge_bg}; color: {badge_fg}; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; text-transform: uppercase; margin-top: 6px; }}
    .greeting {{ font-size: 18px; font-weight: 600; color: #0f172a; margin-top: 0; }}
    .text {{ font-size: 15px; line-height: 1.6; color: #475569; }}
    .event-title {{ font-size: 20px; font-weight: 700; color: #0f172a; margin: 0 0 12px 0; }}
    .item-box {{ background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 18px; margin: 20px 0; font-size: 14px; line-height: 1.6; }}
    .item-row {{ margin-bottom: 6px; }}
    .btn-wrapper {{ text-align: center; margin: 30px 0 24px 0; }}
    .btn {{ background-color: #2563eb; color: #ffffff !important; font-size: 15px; font-weight: 600; text-decoration: none; padding: 14px 32px; border-radius: 8px; display: inline-block; }}
    .footer {{ text-align: center; font-size: 12px; color: #94a3b8; margin-top: 32px; border-top: 1px solid #f1f5f9; padding-top: 20px; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="brand">
      <h1 class="brand-name">WavyGo OS</h1>
      <span class="badge">{badge}</span>
    </div>
    <p class="greeting">Hello {_esc(recipient_name or "there")},</p>
    <p class="text">{_esc(headline)}</p>

    <div class="item-box">
      <p class="event-title">{title_html}</p>
      {rows_html}
    </div>

    <div class="btn-wrapper">
      <a href="{_esc(event_url)}" class="btn" target="_blank">{"View in Calendar" if struck else "Open Event &amp; Reply"}</a>
    </div>

    <div class="footer">
      <p>© 2026 WavyGo OS · Enterprise Workspace Platform</p>
    </div>
  </div>
</body>
</html>"""

    data = {
        "sender": _sender(),
        "to": [{"email": recipient_email, "name": recipient_name or recipient_email}],
        "subject": f"{prefix}: {title} · {when}",
        "htmlContent": html_content,
        "textContent": "\n".join(text_lines),
    }
    headers = {
        "api-key": _brevo_key(),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Mailin-Track": "0",
        "X-Mailin-Click": "0",
    }
    try:
        response = requests.post(BREVO_URL, json=data, headers=headers, timeout=15)
        if response.status_code in (200, 201, 202):
            logger.info("[Email] Calendar %s email sent to %s", kind, recipient_email)
            return True
        logger.error("[Email] Failed to send calendar %s email to %s: %s - %s",
                     kind, recipient_email, response.status_code, response.text)
        return False
    except Exception as e:
        logger.error("[Email] Exception sending calendar %s email: %s", kind, e)
        return False
