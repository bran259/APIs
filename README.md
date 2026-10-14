# APIs

## Supabase item ownership

Database setup is tracked in the `migrations/` directory. Run the SQL files in timestamp order in the Supabase SQL Editor:

1. [`20261012153900_create_items_table.sql`](./migrations/20261012153900_create_items_table.sql) creates `public.items` with a generated numeric ID, item name, optional description, and creation timestamp. It is safe to run when the table already exists.
2. [`20261012154000_add_items_user_id.sql`](./migrations/20261012154000_add_items_user_id.sql) adds a nullable UUID `user_id` reference to `auth.users` and an index for lookups.

New items created through `POST /items/` are assigned to the authenticated user. Existing item rows remain with `user_id = NULL`; assign their owners in Supabase before expecting them to appear in `GET /items/user/{user_id}` or be editable/deletable by an owner.

Item `id` values are numeric database IDs. Use the returned `id` (for example, `/items/2`) for single-item reads, updates, and deletes. The `user_id` owner value is a UUID.

## Tests

Install the development dependencies and run the API tests with:

```sh
pip install -r requirements-dev.txt
pytest
```

The tests use a mocked Supabase client and do not require Supabase credentials or a live database.