## Administrator and permission rules

- Use Django's built-in Group and Permission models.
- Do not create a duplicate custom permission system.
- A SUPER_ADMIN must have is_staff=True and is_superuser=True.
- An ADMIN must have is_staff=True but must not automatically be a superuser.
- Only a Super Admin can create, edit, activate or deactivate Admin accounts.
- Only a Super Admin can assign groups and individual permissions to Admins.
- Regular Admins must not access user or permission administration unless explicitly allowed.
- Deactivating an Admin must not delete their account or audit history.
- Protect management views on both the frontend and backend.
- Hiding a menu item is not sufficient permission enforcement.
- Use Django permission checks in views and templates.
- Prevent a Super Admin from accidentally deactivating their own account.
- Log important administrator management actions.
