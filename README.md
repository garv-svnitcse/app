# WavyGo OS

Internal operating system (ERP) for **WAVYGO MOBILITY SERVICES PRIVATE LIMITED**. One web app for the rental marketplace, tasks, people, opportunities, internal chat, the company calendar, documents, finance, customers, marketing, analytics and an AI assistant.

| | |
| :--- | :--- |
| **Backend** | FastAPI · Motor (async MongoDB) · JWT auth · GridFS for files |
| **Database** | MongoDB (MongoDB Atlas in development and production; a local `mongod` also works) |
| **Frontend** | React 19 (Create React App + CRACO) · Tailwind CSS · shadcn/ui · Recharts |
| **Email** | Brevo transactional API (optional) |
| **AI** | Anthropic Claude API (optional, for WavyGo AI) |
| **Product spec** | [`memory/PRD.md`](memory/PRD.md): scope, roadmap and the contracts that must not change |
| **Long-form docs** | [`docs/ERP_PROJECT_DOCUMENTATION.md`](docs/ERP_PROJECT_DOCUMENTATION.md) |

---

## Contents

- [Quick start](#quick-start)
- [Environment variables](#environment-variables)
- [Roles and permissions](#roles-and-permissions)
- [Modules](#modules)
- [Notifications, email and deep links](#notifications-email-and-deep-links)
- [Security notes](#security-notes)
- [API overview](#api-overview)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Deployment](#deployment)
- [Changelog](#changelog)

---

## Quick start

### Prerequisites
- Python 3.11+ (3.12 used in development and CI)
- Node.js 18+ (22 used in development)
- A MongoDB connection string. The team uses MongoDB Atlas via `MONGO_URL`; a local MongoDB 6+ (`mongod`) is optional and is only needed for the local test suites if you don't point them at another server.

### 1. Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then fill in the values (see Environment variables)
uvicorn server:app --reload --port 8000
```

- API: http://localhost:8000/api (health check: `/api/health`)
- Interactive docs: http://localhost:8000/docs

On start the server:
1. Creates the **Founder** account from `FOUNDER_EMAIL` / `FOUNDER_PASSWORD` / `FOUNDER_NAME`, **only if no Founder account exists yet**. After that the env values are ignored, so a password or profile changed in the app survives restarts. Exactly one Founder is enforced by a unique partial index.
2. Creates all MongoDB indexes (calendar, chat, password resets, vault, finance, CRM, marketing, analytics, task files).
3. Starts three background loops: calendar reminders (every `CALENDAR_REMINDER_INTERVAL_SECONDS`), hourly jobs (Company Vault expiry reminders) and presence (users with no request for 5 minutes are shown offline).

`seed_part2.py` contains optional demo data and never runs automatically.

### 2. Frontend

```bash
cd frontend
npm install                     # CI uses npm ci
npm start                       # http://localhost:3000
```

`npm run build` produces a production build in `frontend/build`.

---

## Environment variables

Names only. Never commit `.env` files, passwords or API keys. [`backend/.env.example`](backend/.env.example) lists them with comments.

### `backend/.env`

| Variable | Required | Purpose |
| :--- | :---: | :--- |
| `MONGO_URL` | ✅ | MongoDB connection string (Atlas `mongodb+srv://…` or local `mongodb://127.0.0.1:27017`). `MONGO_URI`, `MONGODB_URI`, `MONGODB_URL` and `DATABASE_URL` are accepted as fallbacks |
| `DB_NAME` | ✅ | Database name (`DATABASE_NAME` also accepted) |
| `JWT_SECRET` | ✅ | Long random string used to sign tokens |
| `CORS_ORIGINS` | ✅ | Comma-separated frontend origins, or `*` in development |
| `PORT` | | Port used by the Procfile in hosted deployments |
| `FOUNDER_EMAIL` | ✅ | Founder login, used only when the Founder account is first created |
| `FOUNDER_PASSWORD` | ✅ | Founder password for first creation. Always set it; never rely on a default |
| `FOUNDER_NAME` | | Founder display name for first creation |
| `FRONTEND_URL` | ✅ | Public URL of the frontend, used in invitation, password-reset and deep links in emails |
| `BREVO_API_KEY` | | Enables emails. Without it, emails are skipped and invite links are shown in the app to copy instead |
| `BREVO_SENDER_EMAIL` | with Brevo | Verified sender address |
| `BREVO_SENDER_NAME` | | Sender display name |
| `CALENDAR_REMINDER_INTERVAL_SECONDS` | | How often calendar reminders are checked (default `60`) |
| `MESSAGE_EDIT_WINDOW_MINUTES` | | How long senders can edit or delete a chat message (default `15`; `0` = no limit) |
| `VAULT_TZ` | | Time zone for vault expiry dates (default `Asia/Kolkata`) |
| `ANTHROPIC_API_KEY` | for AI | Enables WavyGo AI. Without it the AI page shows a setup message |
| `ANTHROPIC_MODEL` | | Claude model for WavyGo AI (default `claude-opus-5`) |
| `WAVYGO_AI_RATE_LIMIT` | | AI messages per user per hour (default `30`) |
| `WAVYGO_AI_TEST_TOOLS` | tests only | `1` exposes `POST /api/ai/_test/tools/{name}` for scoping tests. Never set in production |

### `frontend/.env`

| Variable | Purpose |
| :--- | :--- |
| `REACT_APP_BACKEND_URL` | Backend origin, e.g. `http://localhost:8000` (the client adds `/api`) |

---

## Roles and permissions

Five roles: **Founder** (exactly one), **Admin**, **Manager**, **Employee**, **Intern**. They are defined once in [`backend/permissions.py`](backend/permissions.py) and mirrored in [`frontend/src/constants/permissions.js`](frontend/src/constants/permissions.js). Change both together. The permission files and router checks are the source of truth; the tables below summarise them.

### Module access

| Module | Founder | Admin | Manager | Employee | Intern |
| :--- | :---: | :---: | :---: | :---: | :---: |
| Dashboard | Company-wide, incl. revenue | Team view | Team view (own department) | Personal | Personal |
| Marketplace (bookings, fleet, vendors, coupons, KYC, support) | ✅ | — | — | — | — |
| Task Board | ✅ all | ✅ all | Own department | "My Tasks": own + create | "Assigned Tasks": assigned only |
| Opportunity Hub | ✅ | ✅ | Own department | "My Opportunities": assigned | — |
| Employees | ✅ | ✅ | Own department | "My Workspace" | "My Workspace" |
| WavyGo Connect (chat) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Calendar | ✅ all events | ✅ all events | Create + visible events | Create + visible events | Visible events |
| Company Vault | ✅ manage | ✅ manage | View (per-item access) | View (per-item access) | View (per-item access) |
| Finance | ✅ | — | — | — | — |
| CRM | ✅ | ✅ | ✅ | — | — |
| Marketing | ✅ | ✅ | ✅ | — | — |
| Analytics | Marketplace + operations | Operations | Operations, own department | — | — |
| Activity Logs | ✅ all | ✅ all | Team (department + self) | — | — |
| WavyGo AI | ✅ | ✅ | ✅ | ✅ | ✅ (answers only from data the role can see) |
| Notifications, Settings, About WavyGo | ✅ | ✅ | ✅ | ✅ ("My Profile") | ✅ ("My Profile") |

### Key actions

| Action | Founder | Admin | Manager | Employee | Intern |
| :--- | :---: | :---: | :---: | :---: | :---: |
| Invite Admin | ✅ | — | — | — | — |
| Invite Manager / Employee / Intern | ✅ | ✅ | — | — | — |
| Edit other employees | ✅ | ✅ | Own department | — | — |
| Deactivate / remove employees, reset their password | ✅ | ✅ (not Admins or the Founder) | — | — | — |
| Create departments | ✅ | ✅ | — | — | — |
| Approve leave, mark others' attendance, performance reviews | ✅ | ✅ | ✅ (own department) | — | — |
| Create tasks | ✅ | ✅ | ✅ | ✅ | — |
| Assign / edit any task | ✅ | ✅ | ✅ | — | — |
| Delete tasks | ✅ | ✅ | — | — | — |
| Create / assign opportunities | ✅ | ✅ | ✅ | — | — |
| Edit any opportunity | ✅ | ✅ | — | — | — |
| Delete opportunities | ✅ | — | — | — | — |
| Create Connect channels / groups | ✅ | ✅ | ✅ | — | — |
| Create / post in announcements | ✅ | ✅ | — | — | — |
| Create calendar events | ✅ | ✅ | ✅ | ✅ | — |
| Edit / delete any calendar event | ✅ | ✅ | — | — | — |
| Upload, edit and set access in Company Vault (`vault.manage`) | ✅ | ✅ | — | — | — |
| Finance view / manage | ✅ | — | — | — | — |
| CRM edit, Marketing manage, Analytics export | ✅ | ✅ | ✅ | — | — |
| Edit company settings | ✅ | — | — | — | — |

Note: the `user.delete` permission (Founder and Admin) matches the remove-employee endpoint (`DELETE /api/employees/{id}`); an Admin cannot remove another Admin or the Founder, and nobody can remove themselves.

---

## Modules

Every page reads real data from the database. Empty data is shown as empty, never as sample numbers. Pages refresh automatically every 30–60 seconds while visible and when you return to the tab. The layout works on desktop and mobile (navigation drawer on small screens), and a Quick Create menu opens create dialogs on any module (`?create=…` links).

### Authentication and accounts
- Email + password login with access tokens (12 hours) and rotating refresh tokens (30 days with "remember me", 1 day without). Sessions are stored server-side and can be revoked.
- Logout revokes the current session, including when the access token has already expired.
- Invitations: 7-day single-use links (`/accept-invite?token=…`), resend and revoke. Invite and reset links keep working even if a stale session on the same browser fails to refresh.
- Password reset by email: single-use links valid for 30 minutes, rate-limited, same response whether or not the email exists (`/reset-password?token=…`). Needs Brevo.
- A password reset (self-service or by Founder/Admin) and deactivation revoke all of that user's sessions. A user deactivated mid-session is signed out on their next request.
- Deep links are preserved through login: opening a protected link while signed out returns you to the same page and query string after signing in.
- Online presence: users are shown online while active, offline after 5 minutes without a request.

Endpoints: `/api/auth` (login, register, refresh, logout, me, attendance, forgot-password, reset-password/validate, reset-password), `/api/users` (list, directory, `PATCH /me`, `POST /me/password`).

### Dashboard
- KPIs, revenue and booking charts, city and vendor performance (Founder only, from Marketplace data); team KPIs for other roles (open and overdue tasks, open pipeline count and value, people). Open tasks are `todo`, `in_progress` and `review` (the same set as the Task Board's "mine" count), so a task in review past its due date counts as overdue.
- Today's tasks, upcoming calendar events (next five, including events already in progress), activity feed, company health and system status.
- A Manager's pending-leave count covers their own department only, matching the Employees module.
- Public login-page live KPIs.

Endpoints: `GET /api/dashboard/stats`, `GET /api/dashboard/live-kpis`.

### Marketplace (Founder only)
- Tabs: Dashboard, Bookings, Customers, Vendors, Vehicles, Cities, Pricing, Coupons, KYC, Support, Reviews, Analytics.
- The Dashboard tab refreshes live every 30 seconds while visible and when you return to the browser tab.
- Bookings: create, status flow `pending → confirmed → active → completed / cancelled`. A booking can redeem a coupon: validity dates, active flag and usage limit are checked and the use is counted atomically. Cancelling a booking gives the coupon use back once (repeat cancels are no-ops).
- Coupons: `valid_from` / `valid_till` must be `YYYY-MM-DD` dates in order; validity is compared with today's IST date.
- KYC workflow for vendors and customers (Aadhaar, PAN, DL, GST, CIN, other), support tickets with priority and status.
- Marketplace alerts (new booking, KYC decision, new support ticket) are sent to the Founder only, not broadcast company-wide.

Endpoints: `/api/marketplace/{cities|vendors|vehicles|customers|pricing|coupons|reviews}` (CRUD), `/bookings`, `/bookings/{id}/status`, `/kyc`, `/support`, `/dashboard`, `/analytics`.

### Task Board
- Kanban (drag and drop), list and calendar views. Statuses `todo`, `in_progress`, `review`, `completed`, `cancelled`; priorities `low`–`urgent`.
- Comments, PDF attachments, links, assignee notifications and assignment emails. Assigning a task to yourself sends no email.
- Visibility follows the role table: all tasks, own department, own/created, or assigned only.
- `?task_id=<id>` opens a task directly; links in notifications and emails use it.
- Date badges: an open task past its due date (including yesterday) shows a red "Overdue" badge. An empty due date is stored as `null` (older tasks holding `""` are read as no due date).

Endpoints: `/api/tasks` (CRUD, `PATCH /{id}/status`, `POST /{id}/comments`, files upload/download/delete, `GET /stats/overview`).

### Opportunity Hub
- Partnership and deal pipeline: type, value, status `open → assigned → in_progress → won / lost / closed`, assignee, notes and documents.
- Each item returns `can_edit` for the current user; the UI hides actions the user can't perform. Employees see and update only opportunities assigned to them.
- Assigning sets status to `assigned` only from `open` (it never downgrades `in_progress`, `won`, `lost` or `closed`). Unassigning puts an `assigned` opportunity back to `open`.
- `?opp=<id>` opens an opportunity directly; notifications and assignment emails link there.

Endpoints: `/api/opportunities` (CRUD, `POST /{id}/assign`, `PATCH /{id}/status`, `GET /stats/overview`).

### Employees
- Directory by department, invitations, activate / deactivate, remove, reset a teammate's password (Founder/Admin).
- Attendance: one-click check-in / check-out with worked hours, attendance records (present, absent, leave, half day, WFH).
- Leave: requests (casual, sick, earned, unpaid) with approval by Founder, Admin or the Manager of the employee's own department. Nobody approves their own leave.
- Performance reviews, departments with head and description editing. Department names match case- and whitespace-insensitively. Renaming a department renames its Connect group, keeping members and history.
- Employees and Interns see "My Workspace" (their own profile, attendance, leave and reviews).

Endpoints: `/api/employees` (list, invite, invitations, resend/revoke, accept-invite, status, reset-password, edit, delete, departments, attendance, check-in/out, leave, performance, stats).

### WavyGo Connect (chat)
- Channels, groups, direct messages and announcements with unread counts and read state.
- **Members-only channels and groups (WhatsApp-style).** New channels and groups are private: only members can see, read and post. On create, pick individual employees and/or whole departments (a snapshot of the department's current active members).
- Member list dialog (admins first), add members or departments, remove members, and leave. The creator is the channel's first admin; `can_manage` tells the UI who can add/remove (channel admins, Founder, Admin). Channel admins can't remove the creator; only Founder/Admin can. A group is never left without an admin.
- **Channel admins**: channel admins, Founder and Admin can make members admins or remove admin rights from the Members dialog. Only Founder/Admin can demote the creator, and the last admin can't step down (department groups excepted).
- **Manage channels** (Founder/Admin): lists every channel, group and announcement channel, including ones they're not in, to manage members and admins. It shows membership metadata only; reading and posting stay members-only, and message previews are never returned to non-members.
- **Make members-only** (Founder/Admin): converts a legacy public channel. Its current members plus its creator keep access (optionally add whole departments at the same time); the creator becomes admin, or the converting user if there is no creator.
- Removed members are notified and the channel disappears from their list on the next poll.
- **Department groups** are created and kept in sync automatically from each employee's department. Their membership follows the org chart, so only Founder/Admin manage them and members can't leave them.
- **Legacy channels** created before members-only existed stay public and joinable by everyone until a Founder/Admin makes them members-only.
- **Announcements** are company-wide broadcasts; only Founder and Admin create and post in them.
- **Edit and delete messages**: hover a message and open its `⋯` menu (Copy text, Edit, Delete). Only the sender can edit (inline; Enter saves, Esc cancels; shown as "(edited)"). The sender can delete their own messages and Founder/Admin can delete any message for moderation (logged in Activity Logs). Senders can edit or delete only within **15 minutes** of sending (`MESSAGE_EDIT_WINDOW_MINUTES`); Founder/Admin moderation deletes have no time limit. The menu shows how many minutes are left. Deleted messages stay in place as "This message was deleted" and their text is erased. Press `↑` in an empty message box to edit your last message.

Endpoints: `/api/connect/channels` (list, create), `/departments`, `/channels/{id}/members` (list, add, `DELETE …/{user_id}` to remove or leave), `/channels/{id}/admins/{user_id}` (`POST` promote, `DELETE` demote), `POST /channels/{id}/members-only`, `/manage/channels` (Founder/Admin), `/dm-users`, `/users`, `/dm/{peer_id}`, `/channels/{id}/messages` (`PATCH` / `DELETE …/{message_id}` to edit or delete), `/join`, `/read`.

### Calendar
- Month, week, day and agenda views; participants; visibility (everyone, department, private); reminders delivered as notifications and email.
- **Drag and drop**: in week / day view, drag across empty slots to create an event for that range, drag an event to move it (across days in week view) or drag its bottom edge to resize; snaps to 15 minutes, Esc cancels. In month view, drag an event onto another day (time and length kept). Moves save immediately with an **Undo** toast. Only the organiser, Founder and Admin can drag an event.
- **RSVP**: invitees reply Going / Maybe / Can't go; the organiser is notified. Event details show a reply summary and each person's answer; the agenda flags events that still need your reply. Moving an event resets replies and tells invitees ("Event rescheduled").
- **Availability**: the event form shows a free/busy timeline for the organiser and invitees on the chosen day, lists clashes and offers the next slot in working hours (09:00–18:00, up to a week ahead) when everyone is free. Private events of others show only as "Busy"; declined invitations don't count.
- **Event form**: duration presets (15m–2h), duplicate an event, Ctrl+Enter to save.
- **Event details**: "Join meeting now" from 10 minutes before start, countdown, copy link, download `.ics` (Google / Outlook / Apple), duplicate.
- **Sidebar**: "Up next for you" (next events with countdown and replies owed), mini calendar with dots on busy days, category and "only my events" / "show cancelled" filters.
- **Search** across title, location and description (`/` focuses the box). Keyboard: `T` today, `←`/`→` previous/next, `M` `W` `D` `A` switch view, `N` new event.
- The agenda starts at local midnight, so meetings earlier today are still listed; events that have ended are faded.
- Editing an event re-arms its reminder only when the start time or reminder offset actually changed (fixing a title doesn't resend the reminder).
- Deep links: `?event=<id>`, `?view=`, `?date=`, `?create=1`.

Endpoints: `/api/calendar/events` (CRUD, date range, participant filter, `q` search, sorting, pagination), `/events/{id}`, `/events/{id}/rsvp`, `/availability` (free/busy), `/month`, `/week`, `/day`, `/agenda`, `/invitees`.

### Company Vault
- Company documents in folders with tags, versions (upload new, download, restore), inline preview, expiry dates and reminders at 30 days, 7 days and on expiry, sent once per stage to every Founder and Admin plus the document's owner. Files up to 25 MB, stored in MongoDB GridFS.
- **Everyone can open the vault; only Founder and Admin upload, create folders, edit, delete and manage access** (`vault.manage`).
- **Per-item access** on every folder and document: everyone, or restricted to any mix of roles, departments and specific employees. Folder access cascades: a document is visible only if both it and its folder admit you. Founder and Admin see everything.
- Items you can't see are hidden from lists and return 404 when opened directly. Restricted items show a badge.
- Items created before access control existed have no access list and stay visible to everyone.
- Folder names are unique vault-wide (case-insensitive). The "already exists" message is only shown to people who can see the clashing folder (Founder/Admin, the only roles that create folders); anyone else would get a neutral "name not available".
- Employees who are individually given access get a "Document shared with you" notification (only newly added people, and only if they can actually open it).
- Deep links: `?doc=<id>`, `?create=1`.

Endpoints: `/api/vault/folders`, `/tags`, `/documents` (upload is multipart with an `access` JSON field), `/documents/{id}`, `/download`, `/versions`, `/versions/{n}/download`, `/versions/{n}/restore`, `/stats`, `POST /reminders/run` (Founder/Admin).

### Finance (Founder only)
- Tabs: Overview, Invoices, Payouts, Vendors, Bills, Statements, Settings.
- **Invoices** from bookings with GST and financial-year numbering, bulk creation, issue / pay / void, print view, CSV export.
- **Payouts**: vendor payout batches from outstanding bookings, mark paid, delete.
- **Vendors** (`finance_vendors`): supplier and payee directory with contact, GSTIN, category and active/inactive status. A vendor can optionally be linked to one Marketplace vendor. Vendor detail shows total spent, outstanding, overdue and a history of bills plus (for a linked Marketplace vendor) booking payouts. A vendor with bills can't be deleted; mark it inactive instead. Inactive vendors can't receive new bills.
- **Vendor bills** (`vendor_bills`): expenses owed to a vendor, status `pending`, `paid` or `cancelled`, with an overdue flag for pending bills past their due date. Bill dates can't be in the future; due date must be on or after the bill date. Only pending bills can be edited or deleted; mark paid (with payment date) or cancel. Filters by vendor, status (including overdue), month, category and text; CSV export.
- **Vendors list** shows total spent, outstanding, overdue, bill count and last bill date per vendor; click a column header to sort. `?tab=vendors&vendor=<id>` opens a vendor's panel directly.
- **Per-vendor statement** (Statement tab in the vendor panel): pick a month or a from/to range to see opening outstanding, bills and linked payouts charged, payments, closing outstanding and a ledger with running balance. CSV export and print view.
- Invoices and payouts can be filtered by Marketplace vendor. The overview includes a payables card (pending and overdue bills), a "Net after vendor bills (MTD)" card and **Top vendors by spend** (last 90 days, ranked by money paid) linking to each vendor.
- **Monthly statements** with CSV export include vendor bills: bills recorded (by bill date) and paid (by payment date), totals by vendor and by category, and **net after bills** = platform commission − bills paid in the month. Cancelled bills are excluded. Editable commission and GST settings.

Endpoints: `/api/finance/settings`, `/invoices` (list, export, eligible, create, bulk, issue, pay, void), `/payouts` (outstanding, create, pay, delete), `/statements` (+ export), `/overview`, `/vendors` (CRUD, `marketplace-options`, `/{id}/statement` + `/statement/export`), `/bills` (list, export, create, edit, pay, cancel, delete).

### CRM (Founder, Admin, Manager)
- Tabs: Overview, Customers, Segments, Follow-ups.
- Customer 360: lifetime value, lifecycle stage, timeline of bookings, tickets, KYC and reviews; notes, tags, follow-ups and saved segments.
- Add, edit and delete customers from the CRM (same `customers` collection as the Marketplace). Emails must be unique; a customer with bookings or support tickets can't be deleted.
- "New follow-up" from the Follow-ups tab with a customer picker.
- Deep links: `?tab=`, `?customer=<id>`.

Endpoints: `/api/crm/meta`, `/overview`, `/customers` (list, get, create, edit, delete), `/customers/{id}/tags`, `/notes`, `/followups`, `/segments`.

### Marketing (Founder, Admin, Manager)
- Campaigns with budget, spend, channels, cities, audience segment and coupons. Results are attributed from bookings that redeemed the campaign's coupons inside the campaign window; until any booking has redeemed a coupon, attribution reports "not supported yet".
- Editing a campaign keeps references (segment, city, coupon, owner) that were renamed or removed since, so unrelated edits never fail.
- Deep links: `?tab=`, `?campaign=<id>`, `?create=1`.

Endpoints: `/api/marketing/meta`, `/overview`, `/campaigns` (CRUD).

### Analytics (Founder, Admin, Manager)
- Marketplace (Founder): KPIs with comparison period, trends, cohort retention, city drill-down, fleet utilisation, booking funnel and heatmap.
- Operations (Founder/Admin, Managers for their own department): tasks, pipeline, attendance and people.
- Range selector **1D / 3D / 7D / 30D / 90D** (the `days` query parameter, kept in the URL as `?days=`), or explicit `from` / `to` dates. Default is the last 30 days. A 1-day range uses hourly buckets; up to ~3 months daily; longer ranges weekly or monthly.
- CSV export of each dataset.

Endpoints: `/api/analytics/meta`, `/marketplace/{summary|trend|cohorts|cities|cities/{city}|fleet|funnel|heatmap}`, `/operations`, `/export/{dataset}`.

### WavyGo AI
- Chat assistant (Claude) with saved conversations, streamed replies (Server-Sent Events) and Markdown rendering.
- Answers from company data through read-only, role-scoped tools: my tasks, search tasks, upcoming events, opportunities summary, team directory, attendance and leave, marketplace KPIs (Founder), recent notifications.
- Rate-limited per user per hour. Needs `ANTHROPIC_API_KEY`.

Endpoints: `/api/ai/status`, `/conversations` (CRUD), `POST /conversations/{id}/messages` (streamed).

### Notifications, Activity Logs, Settings, About
- **Notifications**: in-app list, unread count, mark one or all read. Users can only read and change their own.
- **Activity Logs**: audit trail of changes. Founder/Admin see everything; a Manager sees their department and their own actions. Newest 50 first, with "Load more" for older entries (`GET /api/activity?paged=true&before=<next_cursor>` returns `{items, has_more, next_cursor}`; without `paged` it returns a plain list).
- **Settings**: profile, company profile (Founder edits), theme, security (change password), roles.
- **About WavyGo**: company information page.

---

## Notifications, email and deep links

- In-app notifications are created for assignments, calendar reminders and invitations, channel membership changes, leave decisions, documents shared with you, vault expiry reminders, Marketplace alerts (Founder only) and finance actions. Each carries a link that opens the exact item.
- Deep links used by notifications and emails: `/task-board?task_id=<id>`, `/opportunity-hub?opp=<id>`, `/calendar?event=<id>`, `/company-vault?doc=<id>`, `/crm?customer=<id>`, `/marketing?campaign=<id>`.
- Emails (Brevo): invitations, password resets and reset links, task / opportunity assignments, and calendar emails (invitation, reminder, reschedule, cancellation), each with a deep link. No email is sent for self-assignment. Without `BREVO_API_KEY`, emails are skipped and the app shows invite links to copy.
- All user-supplied text (names, titles, roles) is HTML-escaped in emails, and only `http(s)` meeting links are rendered.
- Set `FRONTEND_URL` to your live site: invitation, assignment and calendar emails use it for links (password-reset links fall back to the requesting site).

---

## Security notes

- Every route except login, refresh, password reset, invite acceptance and the public login-page KPIs requires `Authorization: Bearer <access token>`.
- Role checks are enforced on the server for every action; the frontend only hides what the server would refuse.
- Refresh tokens rotate; sessions are revoked (not deleted) on logout, password reset and deactivation, so old tokens stay dead even after reactivation.
- Invitation acceptance can't take over an existing account; private chats, tasks, opportunities, vault items and notifications are only returned to users allowed to see them. Hidden vault items return 404.
- Nobody approves their own leave; employees can edit only their own safe profile fields.
- The Founder account can't be deactivated, removed or have its password reset by others.
- No secrets in code: all keys come from environment variables. A Brevo key that was once hardcoded was removed and must be rotated.

---

## API overview

All routes are under `/api`. Full, always-current reference: `/docs`.

| Area | Base path | Highlights |
| :--- | :--- | :--- |
| Auth | `/api/auth` | login, refresh (rotating), logout, me, register, forgot / reset password |
| Users | `/api/users` | list, directory, own profile, own password |
| Dashboard | `/api/dashboard` | stats, public live KPIs |
| Marketplace | `/api/marketplace` | cities, vendors, vehicles, customers, pricing, coupons, reviews, bookings, KYC, support, analytics |
| Tasks | `/api/tasks` | CRUD, status (drag-drop), comments, files, stats |
| Employees | `/api/employees` | directory, invitations, status, attendance + check-in/out, leave, performance, departments |
| Opportunities | `/api/opportunities` | CRUD, assign / unassign, status, stats |
| Connect | `/api/connect` | channels, departments, members (add / remove / leave), admins, members-only conversion, manage-all list, DMs, messages, read state |
| Calendar | `/api/calendar` | events CRUD, month / week / day / agenda, search, RSVP, availability (free/busy), invitees |
| Notifications | `/api/notifications` | list, unread count, mark read |
| Activity | `/api/activity` | audit log, modules |
| Settings | `/api/settings` | company profile, roles |
| Company Vault | `/api/vault` | folders, documents, access, versions, downloads, stats, reminders |
| Finance | `/api/finance` | settings, invoices, payouts, vendors, bills, statements, exports |
| CRM | `/api/crm` | customers (CRUD), customer 360, notes, tags, follow-ups, segments |
| Marketing | `/api/marketing` | campaigns, attribution, overview |
| Analytics | `/api/analytics` | marketplace, operations, CSV exports |
| WavyGo AI | `/api/ai` | status, conversations, streamed messages |

---

## Testing

```bash
cd backend
.venv/Scripts/python -m pytest tests/ -k local -q      # Windows path; use .venv/bin/python on macOS/Linux
```

- `pytest.ini` runs tests in parallel with `pytest-xdist` (`-n 2 --dist loadscope`); use `-n 0` to run serially.
- `tests/*_local_test.py` are self-contained: each module starts its own API server on a free port against a throwaway database on the MongoDB at `MONGO_URL` (default `mongodb://127.0.0.1:27017`), and deletes it afterwards. The spawned server runs with `BREVO_API_KEY` blanked, so tests never send real email (email tests mock the Brevo call). See [`tests/local_harness.py`](backend/tests/local_harness.py). Suites: auth, password reset, dashboard, employees, tasks and opportunities, Connect and Marketplace, calendar, vault, finance, CRM and marketing, analytics, AI.
- `tests/backend_test.py`, `backend_part2_test.py` and `rbac_test.py` are end-to-end suites against a running deployment. They are skipped unless `WAVYGO_E2E_URL`, `FOUNDER_EMAIL` and `FOUNDER_PASSWORD` are set (the Founder login on that deployment). Other role accounts come from `E2E_ADMIN_EMAIL`, `E2E_MANAGER_EMAIL`, `E2E_EMPLOYEE_EMAIL`, `E2E_INTERN_EMAIL` (default `<role>@wavygo.in`) with password `E2E_PASSWORD` (default `FOUNDER_PASSWORD`); see [`tests/e2e_accounts.py`](backend/tests/e2e_accounts.py). Don't point them at production data.
- CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the backend suites against a MongoDB 7 service and verifies the frontend build with `npm ci`.

---

## Project structure

```text
backend/
  server.py              FastAPI app: routers, CORS, startup (seed, indexes, reminder / presence loops)
  db.py                  Mongo client + ObjectId helpers
  auth_utils.py          password hashing, JWT, sessions, presence, get_current_user / require_roles
  permissions.py         RBAC matrix (modules + actions)
  hub_utils.py           log_activity, notify, serialize
  email_utils.py         transactional email (Brevo), optional
  dept_groups.py         department Connect groups: create, sync, rename
  models.py              auth / user models
  models_part2.py        module models (tasks, employees, opportunities, calendar, marketplace, ...)
  seed.py                Founder account (first start only) + indexes, runs on startup
  seed_part2.py          optional demo data, never runs automatically
  routers/               one router per module, all mounted under /api
  tests/                 pytest suites (see Testing)
frontend/
  src/App.js             routes; every page renders inside AppShell
  src/pages/             one page per module
  src/components/        layout shell and per-module components (ai, analytics, calendar, crm,
                         finance, marketing, vault), shadcn ui primitives
  src/constants/         nav, permissions, test ids
  src/lib/api.js         axios client (token refresh, deactivated-user sign-out built in)
memory/                  PRD and freeze notes
docs/                    long-form project documentation
```

Frontend routes: `/login`, `/accept-invite`, `/reset-password`, `/dashboard`, `/marketplace`, `/task-board`, `/employees`, `/opportunity-hub`, `/wavygo-connect`, `/calendar`, `/company-vault`, `/finance`, `/crm`, `/marketing`, `/analytics`, `/wavygo-ai`, `/activity-logs`, `/notifications`, `/settings`, `/about-wavygo`.

---

## Deployment

- Backend: `Procfile` runs `uvicorn server:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"`. Trusting forwarded headers from any address is right only when the app is reachable solely through the hosting platform's proxy (Render, Railway, Heroku and similar); otherwise set `--forwarded-allow-ips` to the proxy's address.
- WavyGo AI streams responses (Server-Sent Events); a reverse proxy in front of the backend must not buffer `text/event-stream`.
- Frontend: static build; `frontend/vercel.json` rewrites all routes to `index.html`.
- Set all backend environment variables in the hosting dashboard. `FOUNDER_*` only matters for the very first start against an empty database.

---

## Changelog

### 2026-09-29: chat message edit / delete

- **WavyGo Connect**: edit your own messages (marked "(edited)") and delete them within 15 minutes of sending; Founder/Admin can delete any message at any time. Channel previews follow edits and deletions, and other members see changes on the next poll.

### 2026-09-29: calendar redesign and calendar email

- **Calendar**: drag to create / move / resize (week, day) and move across days (month) with undo; RSVP (Going / Maybe / Can't go) with organiser notifications; free/busy availability with clash detection and "next free slot"; search; "Up next" sidebar; duration presets, duplicate, `.ics` export, join button and countdown; week numbers and busy-day dots. New endpoints `POST /api/calendar/events/{id}/rsvp` and `GET /api/calendar/availability`, plus `q` on every list/view endpoint.
- **Email**: calendar invitation, reminder, reschedule and cancellation emails; invitation, password and assignment emails now HTML-escape user-supplied text (closes an HTML/link injection via task titles and names).
- **Testing**: the local test harness no longer sends real email; new tests for RSVP, availability, search and email escaping.

### 2026-09-29: per-vendor finance, channel admins, gap fixes

- **Finance**: per-vendor statements (month or range, opening/closing outstanding, ledger, CSV, print); monthly statements include vendor bills by vendor and category with net after bills; Overview "Top vendors by spend" and net card; sortable per-vendor columns; `?tab=vendors&vendor=<id>` deep link.
- **Connect**: promote / demote channel admins; Founder/Admin "Manage channels" view (details only, no messages) and converting legacy public channels to members-only; message previews no longer returned to non-members.
- **Company Vault**: expiry reminders go to Founders, Admins and the document owner; duplicate folder names don't reveal hidden folders.
- **Activity Logs**: "Load more" with cursor pagination (`?paged=true&before=`).
- **Marketplace**: Dashboard tab refreshes live.
- **Dashboard / Task Board**: overdue tasks in `review` count as open/overdue; open tasks due yesterday show "Overdue"; empty due dates stored as null.
- **Testing**: end-to-end suites read Founder credentials from `FOUNDER_EMAIL` / `FOUNDER_PASSWORD` (other roles from `E2E_*` variables) instead of hardcoded passwords.

### 2026-09-28: member-only channels, vault access, vendors, QA sweep

- **Connect**: WhatsApp-style members-only channels and groups. Pick people and/or departments on create; member list dialog; add, remove and leave; channel admins and `can_manage`. Legacy channels stay public; department groups sync automatically and follow department renames; announcements stay company-wide (Founder/Admin post). Fixed a crash when creating announcements; removed members drop the channel on the next poll.
- **Company Vault**: opened to all roles for viewing; only Founder/Admin upload, create, edit and manage access (`vault.manage`). Per-item access (everyone, roles, departments, specific employees) with folder cascade; hidden items return 404; restricted badges; legacy items visible to everyone; "shared with you" notifications.
- **Finance**: Vendors (`finance_vendors`) and vendor bills (`vendor_bills`) with Vendors and Bills tabs, vendor detail (total spent, outstanding, overdue, history), mark paid / cancel, CSV export, vendor filters on invoices and payouts, payables card on the overview, optional link to a Marketplace vendor.
- **CRM**: add, edit and delete customers (`POST` / `PATCH` / `DELETE /api/crm/customers`); New follow-up with a customer picker.
- **Analytics**: 1D / 3D / 7D / 30D / 90D range selector (`days` parameter, `?days=` in the URL); hourly buckets for a 1-day range.
- **Calendar**: agenda starts at local midnight so today's earlier meetings show; ended events faded; reminders re-armed only when the time actually changes.
- **Opportunity Hub**: `?opp=<id>` deep links, per-item `can_edit`, unassign, assigning never downgrades status; notifications and emails deep-link.
- **Tasks**: `?task_id=<id>` deep links from notifications and emails; no email for self-assignment.
- **Marketplace**: alerts go to the Founder only; coupon use returned when a booking is cancelled; coupon date validation.
- **Dashboard**: upcoming events include ones in progress; Manager pending-leave counts scoped to their department.
- **Activity Logs**: a Manager's team view always includes their own actions.
- **Auth**: invite / reset links survive a refresh failure; deactivated users are signed out; deep links preserved through login; admin password reset and deactivation revoke sessions; logout revokes the session even with an expired access token.
- **Founder seeding**: `FOUNDER_*` env vars are used only when the Founder account is first created; an existing account is never overwritten on restart.
- **RBAC**: `user.delete` is now Founder and Admin, matching the remove-employee endpoint.
- **Employees**: department renames carry over the department's Connect group; department matching is case- and whitespace-insensitive in more places.

### 2026-09-28 (commit 4661c19)

"feat: complete WavyGo OS modules, security fixes and full QA pass"

- **Calendar**: event retrieval APIs (single event, date range, month, week, day, agenda, participant filters, start-time sort, pagination), full calendar screen, reminders delivered as notifications.
- **New modules**: Company Vault, Finance, CRM, Marketing, Analytics, WavyGo AI, and password reset by email.
- **Security**: fixed invite account takeover, private chat access, leave self-approval, unrestricted employee edits, deactivated logins, session revocation, notification ownership, and task / opportunity visibility; removed a hardcoded Brevo key (must be rotated).
- **Real data only**: removed dashboard fallbacks and placeholder saves; live refresh on every page; mobile navigation drawer; online presence; tolerant department matching with head / description editing.
- **QA**: element-by-element sweep of every page for all five roles (desktop and mobile) with fixes; isolated API test harness (`tests/local_harness.py`); CI runs the local suites against MongoDB and installs the frontend with `npm ci`.

---

## License

No license has been chosen yet. Until one is added, all rights are reserved by WAVYGO MOBILITY SERVICES PRIVATE LIMITED.
