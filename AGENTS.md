# Local Ecommerce MVP

## Project objective

Build a Django ecommerce MVP that sells products to customers located
within a 10 km service radius.

The platform supports:

- Super Admin
- Administrators with module-level permissions
- Own stores
- Partner stores
- Store user accounts
- Products and inventory
- Customers
- Multi-item orders
- Delivery agents
- Manual delivery assignment

## Technology

- Python
- Django
- Django REST Framework
- Bootstrap 5
- SQLite for local development
- PostgreSQL for production
- Django templates for the first MVP
- REST APIs for future mobile applications

## Django applications

- accounts
- locations
- stores
- catalog
- inventory
- customers
- orders
- delivery

## Architecture rules

- Use a custom User model based on AbstractUser.
- Configure AUTH_USER_MODEL before running initial migrations.
- Never save plain-text passwords.
- Use Django Groups and Permissions for administrator permissions.
- Stores must not access another store's products, inventory, or orders.
- Every Product must belong to one Store.
- One Order must contain multiple OrderItems.
- Save product name and price snapshots in OrderItem.
- Use DecimalField for money.
- Do not use FloatField for money.
- Record all stock changes using inventory transactions.
- Use database transactions when placing orders and updating stock.
- Calculate order prices on the backend.
- Do not trust totals sent from the frontend.
- Use latitude and longitude for service-radius validation.
- Add created_at and updated_at fields where appropriate.

## Code conventions

- Keep business logic out of templates.
- Use services for complex order and inventory operations.
- Use TextChoices for status and role choices.
- Use meaningful related_name values.
- Add model constraints where appropriate.
- Add validation for prices and stock quantities.
- Register management models in Django Admin.
- Do not add a dependency without explaining its purpose.
- Keep each implementation task limited to one module.

## Verification

After making changes:

1. Run `python manage.py check`.
2. Run `python manage.py makemigrations --check`.
3. Run relevant tests.
4. Review migrations.
5. Check permission and data-isolation risks.
