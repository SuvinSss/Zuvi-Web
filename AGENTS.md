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

## MVP payment rules

- The MVP supports Cash on Delivery only.
- Checkout must not display online payment options.
- Every new Order must use COD as its payment method.
- New COD orders must have PENDING payment status.
- Payment is marked COLLECTED only after successful delivery and cash collection.
- Customers and Store Users cannot directly mark payment as COLLECTED.
- Only Super Admin or an authorized Admin can update COD payment status.
- Never store card, UPI or banking information.
- Do not integrate a payment gateway in the MVP.
- Keep payment method and payment status fields extensible for future payment methods.
- Record payment-status changes in an audit history.
- Orders must not depend on a Delivery Agent record.
- Delivery Agent and radius validation are postponed features.

## Inventory rules

- Product.stock_quantity is the current available-stock balance.
- Product.stock_quantity must never be edited directly from forms or views.
- All stock changes must use the inventory service layer.
- Every stock change must create an InventoryTransaction.
- InventoryTransaction records are immutable.
- Do not allow transaction records to be edited or deleted normally.
- Stock quantity must never become negative.
- Use transaction.atomic() and select_for_update() when updating stock.
- Store Users may only manage inventory belonging to their Store.
- Admin users require appropriate inventory permissions.
- Quantities must use Decimal, never float.
- Reject zero or negative movement quantities from user input.
- Opening stock must only be recorded once unless explicitly corrected.
- Damaged and expired quantities reduce sellable stock.
- Manual adjustments require a reason.
- Inventory history must preserve the actor, previous balance and new balance.
- Future order stock changes will use the same inventory service.
- Do not implement Cart, Order or Delivery Agent logic in this phase.

## Customer management rules

- Customer authentication must use the custom User model.
- Do not store passwords in the Customer model.
- A Customer profile must have a one-to-one relationship with User.
- Customer Users must always have role CUSTOMER.
- Customer Users must have is_staff=False and is_superuser=False.
- Support self-registration and management-portal registration.
- Store registration source instead of an is_app_user Boolean.
- Customers may have multiple delivery addresses.
- Only one address can be the default address for a Customer.
- Customers must never access another Customer's profile or addresses.
- Customers cannot change role, verification status, active status,
  registration source or created_by.
- Use transaction.atomic() when creating User and Customer records.
- Passwords must be saved using set_password().
- Do not expose passwords in URLs, logs or templates.
- Deactivate Customer accounts instead of deleting them.
- Collect latitude and longitude for future 10 km validation.
- Do not implement cart or orders in this phase.

## Cart, checkout and order rules

- Public customers may browse only approved and active Products belonging
  to active Stores.
- Public pages must never expose Store Price, profit margin, cost,
  commission or internal inventory details.
- A Cart belongs to one authenticated Customer.
- A Cart can contain Products from multiple Stores.
- A Cart must not contain duplicate rows for the same Product.
- Cart quantity changes must be validated against available inventory.
- Cart prices are previews only and must be recalculated during checkout.
- Never trust Product price, discount, subtotal, delivery charge or total
  received from the browser.
- One customer Order can contain multiple OrderItems.
- One Order must be split into one StoreOrder per participating Store.
- OrderItem must save Product name, SKU, unit and price snapshots.
- Checkout must use transaction.atomic().
- Inventory rows must be locked during checkout using select_for_update().
- All Products and stock must be revalidated during checkout.
- Checkout must be idempotent to prevent duplicate Orders.
- Do not directly edit Product stock if Phase 5 provides an inventory
  service.
- Use the Phase 5 inventory service for stock reservation and restoration.
- A failed checkout must not create partial Orders or partial stock changes.
- Order status changes must use a service layer.
- State-changing operations must require POST.
- Customer, Store and Admin permissions must be enforced on the backend.
- Store Users must only access StoreOrders belonging to their Store.
- Customers must only access their own Cart and Orders.
- Order deletion is not allowed.
- Cancellation must preserve Order history and restore inventory exactly once.
- Online payments and Delivery Agent assignment are outside Phase 7.
