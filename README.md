# APIs

## Supabase item ownership

Database setup is tracked in the `migrations/` directory. Run the SQL files in timestamp order in the Supabase SQL Editor:

1. [`20261012153900_create_items_table.sql`](./migrations/20261012153900_create_items_table.sql) creates `public.items` with a generated numeric ID, item name, optional description, and creation timestamp. It is safe to run when the table already exists.
2. [`20261012154000_add_items_user_id.sql`](./migrations/20261012154000_add_items_user_id.sql) adds a nullable UUID `user_id` reference to `auth.users` and an index for lookups.
3. [`20261015114000_enable_items_owner_rls.sql`](./migrations/20261015114000_enable_items_owner_rls.sql) enables row-level security and adds policies that allow authenticated users to read and change only their own items.

Run migrations in timestamp order. All `/items/` routes require a valid bearer access token. Collection and single-item reads are restricted to the authenticated owner. `GET /items/user/{user_id}` is retained for compatibility, but returns 404 unless `{user_id}` matches the authenticated user.

The API validates each token with Supabase and uses that same token for database requests, so the database policies apply to API calls as well. The API also filters reads, updates, and deletes by the authenticated user's ID.

Existing item rows remain with `user_id = NULL` and are inaccessible through owner-only routes until their owners are assigned in Supabase. Item `id` values are numeric database IDs. Use the returned `id` (for example, `/items/2`) for single-item reads, updates, and deletes. The `user_id` owner value is a UUID.

## Tests

Install the development dependencies and run the API tests with:

```sh
pip install -r requirements-dev.txt
pytest
```

The tests use a mocked Supabase client and do not require Supabase credentials or a live database.