// What the logged-in user may do. The backend sends the list at login (user.permissions) and checks
// every request again, so hiding a button here is only for a clean screen, not for security.
export const can = (user, permission) => !!user?.permissions?.includes(permission);

// Manage Access: the Admin (users), and Managers (their team, team access, team activity)
export const canManageAccess = (user) =>
  can(user, "manage_users") || can(user, "grant_team_access") || can(user, "manage_team");

// Lead conversion is reserved for Managers and Salespeople.
export const canCreateSales = (user) => !!user && user.role !== "Admin";

// Direct opportunity creation is available to all signed-in CRM roles, including Admin.
export const canCreateOpportunity = (user) => ["Admin", "Manager", "Salesperson"].includes(user?.role);

// Transfer a lead: the Admin and Managers ("Reassign owner": any lead they can see),
// or a user with "Transfer own leads" (their own leads)
export const canTransferLead = (user, lead) =>
  !!user &&
  !!lead &&
  (user.role === "Admin" || can(user, "reassign_owner") || (can(user, "transfer_leads") && lead.owner_id === user.id));
