// What the logged-in user may do. The backend sends the list at login (user.permissions) and checks
// every request again, so hiding a button here is only for a clean screen, not for security.
export const can = (user, permission) => !!user?.permissions?.includes(permission);
