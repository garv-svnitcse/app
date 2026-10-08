// Exact mirror of backend/permissions.py — RBAC single source of truth (frontend).

export const MODULE_ACCESS = {
  "dashboard":       new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),
  "marketplace":     new Set(["Founder"]),
  "task-board":      new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),
  "opportunity-hub": new Set(["Founder", "Admin", "Manager", "Employee"]),
  "employees":       new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),
  "wavygo-connect":  new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),
  "company-vault":   new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),
  "finance":         new Set(["Founder"]),
  "crm":             new Set(["Founder", "Admin", "Manager"]),
  "marketing":       new Set(["Founder", "Admin", "Manager"]),
  "analytics":       new Set(["Founder", "Admin", "Manager"]),
  "calendar":        new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),
  "wavygo-ai":       new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),
  "about-wavygo":    new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),
  "activity-logs":   new Set(["Founder", "Admin", "Manager"]),
  "notifications":   new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),
  "settings":        new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),
};

export const SIDEBAR_LABELS = {
  "task-board":      { Employee: "My Tasks", Intern: "Assigned Tasks" },
  "opportunity-hub": { Employee: "My Opportunities" },
  "employees":       { Employee: "My Workspace", Intern: "My Workspace" },
  "settings":        { Employee: "My Profile", Intern: "My Profile" },
};

export const ACTIONS = {
  "auth.register":               new Set(["Founder", "Admin"]),
  "auth.change_own_password":    new Set(["Founder", "Admin", "Manager"]),
  "auth.reset_other_password":   new Set(["Founder", "Admin"]),

  "user.invite.founder":         new Set([]),
  "user.invite.admin":           new Set(["Founder"]),
  "user.invite.manager":         new Set(["Founder", "Admin"]),
  "user.invite.employee":        new Set(["Founder", "Admin"]),
  "user.invite.intern":          new Set(["Founder", "Admin"]),
  "user.delete":                 new Set(["Founder", "Admin"]),
  "user.edit_others":            new Set(["Founder", "Admin", "Manager"]),
  "user.edit_self":              new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),

  "marketplace.any":             new Set(["Founder"]),

  "task.create":                 new Set(["Founder", "Admin", "Manager", "Employee"]),
  "task.edit_any":               new Set(["Founder", "Admin", "Manager"]),
  "task.edit_own":               new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),
  "task.delete":                 new Set(["Founder", "Admin"]),
  "task.assign":                 new Set(["Founder", "Admin", "Manager"]),
  "task.comment":                new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),

  "opportunity.create":          new Set(["Founder", "Admin", "Manager"]),
  "opportunity.assign":          new Set(["Founder", "Admin", "Manager"]),
  "opportunity.edit_any":        new Set(["Founder", "Admin"]),
  "opportunity.edit_own":        new Set(["Founder", "Admin", "Manager", "Employee"]),
  "opportunity.delete":          new Set(["Founder"]),

  "employee.invite":             new Set(["Founder", "Admin"]),
  "employee.edit":               new Set(["Founder", "Admin", "Manager"]),
  "employee.view_directory":     new Set(["Founder", "Admin", "Manager"]),
  "employee.view_self":          new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),
  "department.create":           new Set(["Founder", "Admin"]),

  "attendance.mark_self":        new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),
  "attendance.mark_others":      new Set(["Founder", "Admin", "Manager"]),
  "leave.request_self":          new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),
  "leave.approve":               new Set(["Founder", "Admin", "Manager"]),
  "performance.create":          new Set(["Founder", "Admin", "Manager"]),
  "performance.view_self":       new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),

  "connect.create_channel":      new Set(["Founder", "Admin", "Manager"]),
  "connect.create_announcement": new Set(["Founder", "Admin"]),
  "connect.post_announcement":   new Set(["Founder", "Admin"]),
  "connect.send_dm":             new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),

  "calendar.create":             new Set(["Founder", "Admin", "Manager", "Employee"]),
  "calendar.view_all":           new Set(["Founder", "Admin"]),
  "calendar.edit_any":           new Set(["Founder", "Admin"]),
  "calendar.delete_any":         new Set(["Founder", "Admin"]),

  "activity.view_all":           new Set(["Founder", "Admin"]),
  "activity.view_team":          new Set(["Manager"]),

  "vault.view":                  new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),
  "vault.manage":                new Set(["Founder", "Admin"]),

  "finance.view":                new Set(["Founder"]),
  "finance.manage":              new Set(["Founder"]),

  "crm.view":                    new Set(["Founder", "Admin", "Manager"]),
  "crm.edit":                    new Set(["Founder", "Admin", "Manager"]),

  "marketing.view":              new Set(["Founder", "Admin", "Manager"]),
  "marketing.manage":            new Set(["Founder", "Admin", "Manager"]),

  "analytics.view":              new Set(["Founder", "Admin", "Manager"]),
  "analytics.export":            new Set(["Founder", "Admin", "Manager"]),

  "ai.use":                      new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),

  "settings.company_edit":       new Set(["Founder"]),
  "settings.roles_view":         new Set(["Founder", "Admin", "Manager", "Employee", "Intern"]),
};

export function canViewModule(role, key) {
  const set = MODULE_ACCESS[key];
  return !!set && set.has(role);
}

export function can(role, action) {
  const set = ACTIONS[action];
  if (!set) throw new Error(`Unknown action: ${action}`);
  return set.has(role);
}

export function sidebarLabel(moduleKey, defaultLabel, role) {
  return (SIDEBAR_LABELS[moduleKey] && SIDEBAR_LABELS[moduleKey][role]) || defaultLabel;
}
