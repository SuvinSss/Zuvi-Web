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

## Store management rules

- A Store is a business entity and must not contain username or password fields.
- Store login accounts use the custom User model with role STORE_USER.
- Connect users and stores through StoreUser.
- Support multiple users for one Store.
- A Store User may only access their assigned Store.
- Store Users must never view or modify another Store's data.
- Super Admin can manage all Stores.
- Admin requires the appropriate Django permission to manage Stores.
- Deactivate Store Users instead of deleting authentication accounts.
- Suspended or inactive Stores must not access protected Store operations.
- Store creation and primary-user creation must use transaction.atomic().
- Store codes must be unique and generated on the backend.
- Store status changes must be recorded.
- Store status changes must require POST.
- Store images must be validated by file type and size.
- Store latitude and longitude must be collected for future radius validation.
- Never expose temporary passwords through logs or URL parameters.
