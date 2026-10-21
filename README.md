# APIs

## Deployment and configuration

### Requirements

- Python 3.10 or newer.
- A Supabase project with the Auth email/password provider configured as desired by your app.
- A deployment platform that supports running a Python web process and setting environment variables/secrets.

### Configure locally

1. Create a Supabase project and copy its project URL and **publishable/anon key**. Do not use the `service_role` key: the API forwards user access tokens to PostgREST, and the database's row-level security policies must remain effective.
2. Create a local environment file from the committed template:

   ```powershell
   Copy-Item .env.example .env
   ```

3. Edit `.env` and replace `SUPABASE_URL` and `SUPABASE_KEY` with the values from your Supabase project. Set `CORS_ORIGINS` to the exact comma-separated browser origins you use. The template includes examples for common local frontend ports.
4. Install dependencies and start the API from the repository root:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   uvicorn main:app --host 127.0.0.1 --port 8000
   ```

   For local development with auto-reload, use `uvicorn main:app --reload --host 127.0.0.1 --port 8000`. The interactive API documentation is available at `http://127.0.0.1:8000/docs`.

### Apply database migrations

Before starting the deployed API, open the Supabase project's SQL Editor and run the SQL files in `migrations/` in timestamp order, once per database:

1. `20261012153900_create_items_table.sql`
2. `20261012154000_add_items_user_id.sql`
3. `20261015114000_enable_items_owner_rls.sql`

The last migration enables RLS and recreates its four named policies, so it is safe to re-run. Existing rows with a `NULL` `user_id` remain inaccessible through owner-only routes until you assign their owners.

### Production Supabase Auth and abuse protection

Use these production policies in the Supabase Dashboard's Auth settings:

- Set the minimum password length to **12 characters**. The API enforces this for signup; login still accepts passwords of 6 or more characters so existing accounts can sign in and change weaker passwords.
- **Require email confirmation** before a new account can sign in. Configure production SMTP and the allowed redirect URLs so confirmation messages can be delivered and safely return users to the frontend.
- Keep Supabase Auth's own request/email rate limits enabled and configure CAPTCHA for public sign-up if your deployment needs stronger bot protection.

The API also applies a sliding-window limit per client IP: **5 signups per minute** and **10 login attempts per minute**. Excess requests receive the standard `429` error and a `Retry-After` header. This limiter is in process memory, so it is an additional control for a single API process, not a shared counter. In production, configure the HTTPS gateway/load balancer/WAF to enforce at least the same per-IP limits across all workers and replicas. Ensure the gateway strips and replaces incoming forwarded-IP headers, and configure Uvicorn to trust only that gateway's known IPs; otherwise clients may spoof their rate-limit identity. Alert on sustained `429` spikes without logging request bodies, passwords, or tokens.

These Auth settings are project-level and cannot be applied or verified from this repository. Set and verify them in the Supabase project before production deployment.

### Verify RLS and owner isolation

After applying the migrations, run this in the Supabase SQL Editor to verify that RLS is enabled and all four policies exist:

```sql
SELECT
    c.relrowsecurity AS rls_enabled,
    p.polname,
    p.polcmd,
    pg_get_expr(p.polqual, p.polrelid) AS using_expression,
    pg_get_expr(p.polwithcheck, p.polrelid) AS check_expression
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
LEFT JOIN pg_policy AS p ON p.polrelid = c.oid
WHERE n.nspname = 'public'
  AND c.relname = 'items'
ORDER BY p.polname;
```

Confirm `rls_enabled` is `true` and the results include the read, create, update, and delete policies. Each policy must compare `auth.uid()` with `user_id`; update must constrain both the existing row and the new row.

Then verify the deployed API using **two test accounts**:

1. Sign up and log in as test user A; save A's access token locally. Create an item as A and record its returned item ID.
2. Sign up and log in as test user B; save B's access token locally.
3. With A's token, confirm `GET /items/{item_id}` returns the item. With B's token, confirm that same request returns `404`.
4. With B's token, try `PUT`, `PATCH`, and `DELETE` on A's item ID. Each must return `404`, and the item must still be readable with A's token afterward.
5. Confirm B's `GET /items/` does not include A's item, and that B can create, read, update, and delete B's own test item.
6. Delete any remaining test data and accounts when done.

Send tokens only in the `Authorization: Bearer <token>` header. Do not put real credentials or tokens in source control, screenshots, logs, or shared chat. The repository's automated tests mock Supabase; they do not replace this live project check.

### Deploy

1. Configure the deployment's secret/environment-variable settings with `SUPABASE_URL`, `SUPABASE_KEY`, and `CORS_ORIGINS`. Use the same Supabase project where you applied the migrations. `CORS_ORIGINS` must contain the deployed frontend's exact origin(s), including scheme and any non-default port; do not use `*`.
2. Install production dependencies with `python -m pip install -r requirements.txt`.
3. Set the web process start command to:

   ```sh
   uvicorn main:app --host 0.0.0.0 --port $PORT
   ```

   Configure the platform to provide `PORT` (commonly `8000` if it requires an explicit value). Do not use `--reload` in production. Serve the app behind the platform's HTTPS/reverse-proxy layer.
4. Confirm the deployment starts successfully, then check `/docs` and make an authenticated request to verify Supabase connectivity and the applied owner RLS policies.

### Health checks, logs, and alerts

- Configure the platform's **liveness** probe as `GET /health/live`. It returns `200` while the app process is responding and intentionally does not depend on Supabase.
- Configure its **readiness** probe as `GET /health/ready`. It performs a zero-row query against `public.items`, returning `200` only when the Supabase REST/database path and table are reachable; failures return a generic `503`. It does not validate user authentication or replace the two-account RLS verification above.
- Use the platform's application log collection for the Uvicorn stdout/stderr streams. Unexpected application errors and Supabase/database failures include an error log with a traceback; expected client errors are not logged as server failures. Do not enable request-header/body logging for Authorization headers, passwords, or tokens.
- Create platform alerts for sustained readiness failures, elevated HTTP `5xx` rates, and recurring log messages such as `Database operation ... failed`, `Supabase operation ... failed`, and `Unhandled request error`. Choose the evaluation window and notification destination in your hosting platform; investigate Supabase status and deployment changes when they fire. Alert separately on unusual authentication failure or rate-limit spikes, but avoid paging on individual `401` responses.

Never commit `.env` or real credentials. `.env` and other `.env.*` files are ignored by Git; `.env.example` contains placeholders only. The repository previously tracked `.env`, so removing it from the current Git tree does **not** remove credentials from earlier commits. If that file ever contained real credentials, rotate the Supabase key in the Supabase dashboard and update your local/deployment secrets.

## Supabase item ownership

Database setup is tracked in the `migrations/` directory. Run the SQL files in timestamp order in the Supabase SQL Editor:

1. [`20261012153900_create_items_table.sql`](./migrations/20261012153900_create_items_table.sql) creates `public.items` with a generated numeric ID, item name, optional description, and creation timestamp. It is safe to run when the table already exists.
2. [`20261012154000_add_items_user_id.sql`](./migrations/20261012154000_add_items_user_id.sql) adds a nullable UUID `user_id` reference to `auth.users` and an index for lookups.
3. [`20261015114000_enable_items_owner_rls.sql`](./migrations/20261015114000_enable_items_owner_rls.sql) enables row-level security and adds policies that allow authenticated users to read and change only their own items.

Run migrations in timestamp order. All `/items/` routes require a valid bearer access token. Collection and single-item reads are restricted to the authenticated owner. `GET /items/user/{user_id}` is retained for compatibility, returns 404 unless `{user_id}` matches the authenticated user, and uses the same pagination as `GET /items/`.

The API validates each token with Supabase and uses that same token for database requests, so the database policies apply to API calls as well. The API also filters reads, updates, and deletes by the authenticated user's ID.

`GET /items/` and `GET /items/user/{user_id}` accept `limit` and `offset` query parameters for pagination. The default page size is 50; limits must be between 1 and 100, and offset must be non-negative. Results are ordered by item ID and returned as `{"data": [...], "pagination": {"limit": 20, "offset": 0, "next_offset": 20}}`. Follow `next_offset` to fetch the next page; it is `null` when there are no more results.

Item read and write endpoints return item payloads in a `data` envelope. `PUT /items/{item_id}` remains a full replacement and requires `name`; omitted `description` is reset to `null`. Use `PATCH /items/{item_id}` to update only the provided `name` and/or `description` fields. Empty patches and `null` names are rejected. Item names are trimmed and cannot be empty or whitespace-only. Signup/login return `502` with a safe error if Supabase omits the user ID or, for login, the session access token. Validation and HTTP errors use `{"error": {"code": "...", "message": "..."}}`.

Existing item rows remain with `user_id = NULL` and are inaccessible through owner-only routes until their owners are assigned in Supabase. Item `id` values are numeric database IDs. Use the returned `id` (for example, `/items/2`) for single-item reads, updates, and deletes. The `user_id` owner value is a UUID.

## CORS configuration

CORS allows `http://localhost:3000` and `http://localhost:5173` by default as frontend development examples. Set `CORS_ORIGINS` to a comma-separated list of exact frontend origins when your frontend is running elsewhere, for example `CORS_ORIGINS=http://localhost:3000,https://app.example.com`. Include the scheme and port when applicable, and do not include URL paths or trailing slashes. Credentials remain enabled, but origins are never wildcarded.

## Error responses

Invalid or expired bearer tokens return `401`; attempts to access another user's data return `403` or `404` without revealing whether a resource exists. Invalid request data returns `422`, database conflicts return `409`, and malformed responses from Supabase Auth return `502`. All error responses use the same `error.code` and `error.message` shape. Unexpected Supabase/database failures return a generic `503` response; exception details are logged by the API and are not included in the response.

## Tests

Install the development dependencies and run the API tests with:

```sh
pip install -r requirements-dev.txt
pytest
```

The tests use a mocked Supabase client and do not require Supabase credentials or a live database.