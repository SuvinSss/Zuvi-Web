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

## Product catalogue rules

- Every Product must belong to one Store.
- Only active Store Users belonging to the Product's Store can manage it.
- Store Users must never access another Store's Products.
- Store Users can enter Store Price but cannot approve Products.
- Admin or Super Admin controls profit margin, discount and final price.
- Product prices must use DecimalField.
- Never use FloatField for prices.
- Price calculations must happen on the backend.
- final_price must never be accepted directly from Store User input.
- Store Users must not change management pricing fields.
- New Products submitted by Store Users default to PENDING.
- Only approved and active Products will later be displayed to Customers.
- Save multiple images through ProductImage.
- Validate image type and file size.
- Product category supports parent and child categories.
- Product SKU must be unique within a Store.
- Product code must be globally unique and generated on the backend.
- Product status changes must be recorded.
- Important pricing changes must be recorded.
- Use queryset filtering for Store isolation.
- Do not implement cart, checkout or ordering in this phase.
