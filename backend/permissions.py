from __future__ import annotations
"""Central RBAC permission matrix for WavyGo OS.

Single source of truth for module visibility and per-action permissions.
Frontend mirrors this in src/constants/permissions.js.
"""

MODULE_ACCESS = {
    "dashboard":       {"Founder", "Admin", "Manager", "Employee", "Intern"},
    "marketplace":     {"Founder"},
    "task-board":      {"Founder", "Admin", "Manager", "Employee", "Intern"},
    "opportunity-hub": {"Founder", "Admin", "Manager", "Employee"},
    "employees":       {"Founder", "Admin", "Manager", "Employee", "Intern"},
    "wavygo-connect":  {"Founder", "Admin", "Manager", "Employee", "Intern"},
    "company-vault":   {"Founder", "Admin", "Manager", "Employee", "Intern"},
    "finance":         {"Founder"},
    "crm":             {"Founder", "Admin", "Manager"},
    "marketing":       {"Founder", "Admin", "Manager"},
    "analytics":       {"Founder", "Admin", "Manager"},
    "calendar":        {"Founder", "Admin", "Manager", "Employee", "Intern"},
    "wavygo-ai":       {"Founder", "Admin", "Manager", "Employee", "Intern"},
    "about-wavygo":    {"Founder", "Admin", "Manager", "Employee", "Intern"},
    "activity-logs":   {"Founder", "Admin", "Manager"},
    "notifications":   {"Founder", "Admin", "Manager", "Employee", "Intern"},
    "settings":        {"Founder", "Admin", "Manager", "Employee", "Intern"},
}

SIDEBAR_LABELS = {
    "task-board":      {"Employee": "My Tasks", "Intern": "Assigned Tasks"},
    "opportunity-hub": {"Employee": "My Opportunities"},
    "employees":       {"Employee": "My Workspace", "Intern": "My Workspace"},
    "settings":        {"Employee": "My Profile", "Intern": "My Profile"},
}

ACTIONS = {
    "auth.register":                {"Founder", "Admin"},
    "auth.change_own_password":     {"Founder", "Admin", "Manager"},
    "auth.reset_other_password":    {"Founder", "Admin"},

    "user.invite.founder":          set(),
    "user.invite.admin":            {"Founder"},
    "user.invite.manager":          {"Founder", "Admin"},
    "user.invite.employee":         {"Founder", "Admin"},
    "user.invite.intern":           {"Founder", "Admin"},
    "user.delete":                  {"Founder", "Admin"},
    "user.edit_others":             {"Founder", "Admin", "Manager"},
    "user.edit_self":               {"Founder", "Admin", "Manager", "Employee", "Intern"},

    "marketplace.any":              {"Founder"},

    "task.create":                  {"Founder", "Admin", "Manager", "Employee"},
    "task.edit_any":                {"Founder", "Admin", "Manager"},
    "task.edit_own":                {"Founder", "Admin", "Manager", "Employee", "Intern"},
    "task.delete":                  {"Founder", "Admin"},
    "task.assign":                  {"Founder", "Admin", "Manager"},
    "task.comment":                 {"Founder", "Admin", "Manager", "Employee", "Intern"},

    "opportunity.create":           {"Founder", "Admin", "Manager"},
    "opportunity.assign":           {"Founder", "Admin", "Manager"},
    "opportunity.edit_any":         {"Founder", "Admin"},
    "opportunity.edit_own":         {"Founder", "Admin", "Manager", "Employee"},
    "opportunity.delete":           {"Founder"},

    "employee.invite":              {"Founder", "Admin"},
    "employee.edit":                {"Founder", "Admin", "Manager"},
    "employee.view_directory":      {"Founder", "Admin", "Manager"},
    "employee.view_self":           {"Founder", "Admin", "Manager", "Employee", "Intern"},
    "department.create":            {"Founder", "Admin"},

    "attendance.mark_self":         {"Founder", "Admin", "Manager", "Employee", "Intern"},
    "attendance.mark_others":       {"Founder", "Admin", "Manager"},
    "leave.request_self":           {"Founder", "Admin", "Manager", "Employee", "Intern"},
    "leave.approve":                {"Founder", "Admin", "Manager"},
    "performance.create":           {"Founder", "Admin", "Manager"},
    "performance.view_self":        {"Founder", "Admin", "Manager", "Employee", "Intern"},

    "connect.create_channel":       {"Founder", "Admin", "Manager"},
    "connect.create_announcement":  {"Founder", "Admin"},
    "connect.post_announcement":    {"Founder", "Admin"},
    "connect.send_dm":              {"Founder", "Admin", "Manager", "Employee", "Intern"},

    "calendar.create":              {"Founder", "Admin", "Manager", "Employee"},
    "calendar.view_all":            {"Founder", "Admin"},
    "calendar.edit_any":            {"Founder", "Admin"},
    "calendar.delete_any":          {"Founder", "Admin"},

    "activity.view_all":            {"Founder", "Admin"},
    "activity.view_team":           {"Manager"},

    "vault.view":                   {"Founder", "Admin", "Manager", "Employee", "Intern"},
    "vault.manage":                 {"Founder", "Admin"},

    "finance.view":                 {"Founder"},
    "finance.manage":               {"Founder"},

    "crm.view":                     {"Founder", "Admin", "Manager"},
    "crm.edit":                     {"Founder", "Admin", "Manager"},

    "marketing.view":               {"Founder", "Admin", "Manager"},
    "marketing.manage":             {"Founder", "Admin", "Manager"},

    "analytics.view":               {"Founder", "Admin", "Manager"},
    "analytics.export":             {"Founder", "Admin", "Manager"},

    "ai.use":                       {"Founder", "Admin", "Manager", "Employee", "Intern"},

    "settings.company_edit":        {"Founder"},
    "settings.roles_view":          {"Founder", "Admin", "Manager", "Employee", "Intern"},
}


def can_view_module(role, key):
    return role in MODULE_ACCESS.get(key, set())


def can(role, action):
    if action not in ACTIONS:
        raise ValueError(f"Unknown action: {action}")
    return role in ACTIONS[action]


def sidebar_label(module_key, default_label, role):
    return SIDEBAR_LABELS.get(module_key, {}).get(role, default_label)
