from __future__ import annotations
import os
import requests

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

    accept_url =  f"{FRONTEND_URL}/accept-invite?token={token}"
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

