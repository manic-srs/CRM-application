// What the logged-in user may do. The backend sends the list at login (user.permissions) and checks
// every request again, so hiding a button here is only for a clean screen, not for security.
export const can = (user, permission) => !!user?.permissions?.includes(permission);

// Admins can create and edit leads, but opportunities still come from Managers and Salespeople
// converting a lead.
export const canCreateSales = (user) => !!user && user.role !== "Admin";

// Transfer a lead: the Admin and Managers ("Reassign owner": any lead they can see),
// or a user with "Transfer own leads" (their own leads)
export const canTransferLead = (user, lead) =>
  !!user &&
  !!lead &&
  (user.role === "Admin" || can(user, "reassign_owner") || (can(user, "transfer_leads") && lead.owner_id === user.id));
