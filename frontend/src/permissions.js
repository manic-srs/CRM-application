// What the logged-in user may do. The backend sends the list at login (user.permissions) and checks
// every request again, so hiding a button here is only for a clean screen, not for security.
export const can = (user, permission) => !!user?.permissions?.includes(permission);

// Admins manage the CRM but don't sell: they can edit leads and opportunities, not create them
// (opportunities are created by converting a lead).
export const canCreateSales = (user) => !!user && user.role !== "Admin";
