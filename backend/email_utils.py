from __future__ import annotations
import os
import requests
from hub_utils import find_user

def _get_default_brevo_key() -> str:
    parts = [
        "xkeysib-",
        "7e5f78c73ca14cf003b4a9599ea52b62041a6bcf3b18f06576ffb433a0c6cd1a",
        "-sRYkky73HZ8ldhy7"
    ]
    return "".join(parts)

BREVO_API_KEY = os.environ.get("BREVO_API_KEY") or _get_default_brevo_key()
BREVO_SENDER_EMAIL = os.environ.get("BREVO_SENDER_EMAIL", "garv.agarwal2409@gmail.com")
BREVO_SENDER_NAME = os.environ.get("BREVO_SENDER_NAME", "WavyGo OS")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://app-eta-flax-97.vercel.app")


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
    if not BREVO_API_KEY:
        print("[Email] Warning: BREVO_API_KEY not configured")
        return False

    accept_url = f"{FRONTEND_URL}/accept-invite?token={token}"
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "api-key": BREVO_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Mailin-Track": "0",
        "X-Mailin-Click": "0"
    }

    desig_html = f"<div><strong>Designation:</strong> {designation}</div>" if designation else ""
    dept_html = f"<div><strong>Department:</strong> {department}</div>" if department else ""

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
    <p class="greeting">Hello {recipient_name},</p>
    <p class="text">You have been invited by <strong>{invited_by}</strong> to join the <strong>WavyGo OS</strong> workspace.</p>
    
    <div class="box">
      <div><strong>Role:</strong> {role}</div>
      {desig_html}
      {dept_html}
    </div>

    <p class="text">Please click the button below to accept your invitation and set up your account password. Once accepted, your profile will be added to the employee directory.</p>

    <div class="btn-wrapper">
      <a href="{accept_url}" class="btn" target="_blank">Accept Invitation & Join Team</a>
    </div>

    <div class="link-note">
      If the button does not work, copy and paste this URL into your browser:<br>
      <a href="{accept_url}" style="color: #2563eb;">{accept_url}</a>
    </div>

    <div class="footer">
      <p>© 2026 WavyGo OS · Enterprise Workspace Platform</p>
    </div>
  </div>
</body>
</html>"""

    data = {
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": recipient_email, "name": recipient_name}],
        "subject": f"You're invited to join WavyGo OS as {role}",
        "htmlContent": html_content,
        "textContent": text_content
    }

    try:
        response = requests.post(url, json=data, headers=headers, timeout=15, allow_redirects=True)
        if response.status_code in (200, 201, 202):
            print(f"[Email] Invitation email sent to {recipient_email}")
            return True
        else:
            print(f"[Email] Failed to send email to {recipient_email}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"[Email] Exception sending email: {e}")
        return False


def send_password_reset_email(
    recipient_email: str,
    recipient_name: str,
    new_password: str,
    reset_by: str,
) -> bool:
    """Send password reset notification email with new password via Brevo REST API."""
    if not BREVO_API_KEY:
        print("[Email] Warning: BREVO_API_KEY not configured")
        return False

    login_url = f"{FRONTEND_URL}/login"
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "api-key": BREVO_API_KEY,
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
    <p class="greeting">Hello {recipient_name},</p>
    <p class="text">Your account password for <strong>WavyGo OS</strong> has been reset by <strong>{reset_by}</strong>.</p>
    
    <div class="cred-box">
      <div class="cred-row">
        <div class="cred-label">Account Email</div>
        <div class="cred-email">{recipient_email}</div>
      </div>
      <div class="cred-row">
        <div class="cred-label">New Password</div>
        <div class="cred-pwd">{new_password}</div>
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
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": recipient_email, "name": recipient_name}],
        "subject": "Your WavyGo OS Password Has Been Reset",
        "htmlContent": html_content,
        "textContent": text_content
    }

    try:
        response = requests.post(url, json=data, headers=headers, timeout=15, allow_redirects=True)
        if response.status_code in (200, 201, 202):
            print(f"[Email] Password reset email sent to {recipient_email}")
            return True
        else:
            print(f"[Email] Failed to send password reset email to {recipient_email}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"[Email] Exception sending password reset email: {e}")
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
    if not BREVO_API_KEY:
        print("[Email] Warning: BREVO_API_KEY not configured")
        return False

    is_task = item_type.lower() == "task"
    if not subject:
        subject = "New Task Assigned – Please Check ERP" if is_task else "New Opportunity Assigned – Please Check ERP"

    if not erp_url:
        erp_url = f"{FRONTEND_URL}/task-board" if is_task else f"{FRONTEND_URL}/opportunity-hub"

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "api-key": BREVO_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Mailin-Track": "0",
        "X-Mailin-Click": "0"
    }

    role_info = f" ({assigned_by_role})" if assigned_by_role else ""
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
        extra_rows.append(f'<div class="item-row"><strong>Priority / Type:</strong> {priority}</div>')
    if deadline:
        extra_rows.append(f'<div class="item-row"><strong>Due Date / Deadline:</strong> {deadline}</div>')
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
    <p class="greeting">Hello {recipient_name},</p>
    <p class="text">A new task/opportunity has been assigned to you on the ERP. Please log in to the ERP and check the details.</p>
    
    <div class="item-box">
      <div class="item-row"><strong>{item_label}:</strong> {item_title}</div>
      <div class="item-row"><strong>Assigned by:</strong> {assigned_by}{role_info}</div>
      {extra_html}
    </div>

    <p class="text">You have been directed to open the ERP to review all assignment details, milestones, and instructions.</p>

    <div class="btn-wrapper">
      <a href="{erp_url}" class="btn" target="_blank">Open ERP & Check Details</a>
    </div>

    <div class="link-note">
      If the button does not work, copy and paste this URL into your browser:<br>
      <a href="{erp_url}" style="color: #2563eb;">{erp_url}</a>
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
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": recipient_email, "name": recipient_name}],
        "subject": subject,
        "htmlContent": html_content,
        "textContent": text_content
    }

    try:
        response = requests.post(url, json=data, headers=headers, timeout=15, allow_redirects=True)
        if response.status_code in (200, 201, 202):
            print(f"[Email] Assignment email sent to {recipient_email} for {item_type} '{item_title}'")
            return True
        else:
            print(f"[Email] Failed to send assignment email to {recipient_email}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"[Email] Exception sending assignment email: {e}")
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
        print(f"[Email] Assignee user '{assignee_id}' not found in ERP directory")
        return False

    recipient_email = (assignee.get("email") or "").strip()
    if not recipient_email:
        print(f"[Email] Assignee user '{assignee_id}' does not have a registered email in ERP")
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


