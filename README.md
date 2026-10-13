# APIs

## Supabase item ownership

Run [`migrations/20261012154000_add_items_user_id.sql`](./migrations/20261012154000_add_items_user_id.sql) in the Supabase SQL Editor before using the user-items endpoint or creating items. It adds a nullable UUID `user_id` reference to `auth.users` and an index for lookups.

New items created through `POST /items/` are assigned to the authenticated user. Existing item rows remain with `user_id = NULL`; assign their owners in Supabase before expecting them to appear in `GET /items/user/{user_id}` or be editable/deletable by an owner.

## Tests

Install the development dependencies and run the API tests with:

```sh
pip install -r requirements-dev.txt
pytest
```

The tests use a mocked Supabase client and do not require Supabase credentials or a live database.