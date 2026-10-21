import os
from uuid import uuid4
from urllib.parse import urlparse

import pytest
from postgrest.exceptions import APIError
from supabase import Client, create_client


INTEGRATION_ENV_VARS = (
    "SUPABASE_INTEGRATION_URL",
    "SUPABASE_INTEGRATION_ANON_KEY",
    "SUPABASE_INTEGRATION_PROJECT_REF",
    "SUPABASE_INTEGRATION_USER_A_EMAIL",
    "SUPABASE_INTEGRATION_USER_A_PASSWORD",
    "SUPABASE_INTEGRATION_USER_B_EMAIL",
    "SUPABASE_INTEGRATION_USER_B_PASSWORD",
)


@pytest.fixture(scope="module")
def integration_clients() -> tuple[Client, Client, str, str]:
    configured = {name: os.getenv(name) for name in INTEGRATION_ENV_VARS}
    if not any(configured.values()):
        pytest.skip("Supabase integration environment is not configured.")

    missing = [name for name, value in configured.items() if not value]
    if missing:
        pytest.fail(
            "Incomplete Supabase integration configuration; missing: "
            + ", ".join(missing)
        )
    settings = {name: os.environ[name] for name in INTEGRATION_ENV_VARS}

    project_host = urlparse(settings["SUPABASE_INTEGRATION_URL"]).hostname
    expected_host = f"{settings['SUPABASE_INTEGRATION_PROJECT_REF']}.supabase.co"
    if project_host != expected_host:
        pytest.fail(
            "SUPABASE_INTEGRATION_URL must target the project identified by "
            "SUPABASE_INTEGRATION_PROJECT_REF."
        )

    client_a = create_client(
        settings["SUPABASE_INTEGRATION_URL"],
        settings["SUPABASE_INTEGRATION_ANON_KEY"],
    )
    client_b = create_client(
        settings["SUPABASE_INTEGRATION_URL"],
        settings["SUPABASE_INTEGRATION_ANON_KEY"],
    )
    session_a = client_a.auth.sign_in_with_password(
        {
            "email": settings["SUPABASE_INTEGRATION_USER_A_EMAIL"],
            "password": settings["SUPABASE_INTEGRATION_USER_A_PASSWORD"],
        }
    ).session
    session_b = client_b.auth.sign_in_with_password(
        {
            "email": settings["SUPABASE_INTEGRATION_USER_B_EMAIL"],
            "password": settings["SUPABASE_INTEGRATION_USER_B_PASSWORD"],
        }
    ).session
    if session_a is None or session_b is None:
        pytest.fail("Both Supabase integration users must have active sessions.")

    client_a.postgrest.auth(session_a.access_token)
    client_b.postgrest.auth(session_b.access_token)
    return client_a, client_b, session_a.user.id, session_b.user.id


def test_items_migrations_and_owner_rls(integration_clients):
    client_a, client_b, user_a_id, user_b_id = integration_clients
    marker = f"rls-integration-{uuid4()}"
    item_a_id = None
    item_b_id = None
    forged_item_id = None

    try:
        item_a = (
            client_a.table("items")
            .insert({"name": f"{marker}-a", "user_id": user_a_id})
            .select("id")
            .execute()
            .data[0]
        )
        item_a_id = item_a["id"]

        own_read = (
            client_a.table("items")
            .select("id,name,user_id")
            .eq("id", item_a_id)
            .execute()
            .data
        )
        assert own_read == [
            {"id": item_a_id, "name": f"{marker}-a", "user_id": user_a_id}
        ]

        hidden_from_b = (
            client_b.table("items")
            .select("id")
            .eq("id", item_a_id)
            .execute()
            .data
        )
        assert hidden_from_b == []

        cross_user_update = (
            client_b.table("items")
            .update({"name": f"{marker}-tampered"})
            .eq("id", item_a_id)
            .select("id")
            .execute()
            .data
        )
        assert cross_user_update == []

        unchanged = (
            client_a.table("items")
            .select("name")
            .eq("id", item_a_id)
            .execute()
            .data
        )
        assert unchanged == [{"name": f"{marker}-a"}]

        cross_user_delete = (
            client_b.table("items")
            .delete()
            .eq("id", item_a_id)
            .select("id")
            .execute()
            .data
        )
        assert cross_user_delete == []
        still_exists = (
            client_a.table("items")
            .select("id")
            .eq("id", item_a_id)
            .execute()
            .data
        )
        assert still_exists == [{"id": item_a_id}]

        try:
            forged_item = (
                client_b.table("items")
                .insert({"name": f"{marker}-forged", "user_id": user_a_id})
                .select("id")
                .execute()
                .data[0]
            )
            forged_item_id = forged_item["id"]
            pytest.fail("RLS allowed user B to create an item owned by user A.")
        except APIError as exc:
            assert exc.code == "42501"

        item_b = (
            client_b.table("items")
            .insert({"name": f"{marker}-b", "user_id": user_b_id})
            .select("id")
            .execute()
            .data[0]
        )
        item_b_id = item_b["id"]
        try:
            (
                client_b.table("items")
                .update({"user_id": user_a_id})
                .eq("id", item_b_id)
                .select("id")
                .execute()
            )
            pytest.fail("RLS allowed user B to transfer an item to user A.")
        except APIError as exc:
            assert exc.code == "42501"

        still_owned_by_b = (
            client_b.table("items")
            .select("user_id")
            .eq("id", item_b_id)
            .execute()
            .data
        )
        assert still_owned_by_b == [{"user_id": user_b_id}]

        assert (
            client_b.table("items")
            .select("id")
            .eq("id", item_b_id)
            .execute()
            .data
            == [{"id": item_b_id}]
        )
        assert (
            client_b.table("items")
            .update({"name": f"{marker}-b-updated"})
            .eq("id", item_b_id)
            .select("id")
            .execute()
            .data
            == [{"id": item_b_id}]
        )
        assert (
            client_b.table("items")
            .delete()
            .eq("id", item_b_id)
            .select("id")
            .execute()
            .data
            == [{"id": item_b_id}]
        )
        item_b_id = None
    finally:
        if item_a_id is not None:
            deleted = (
                client_a.table("items")
                .delete()
                .eq("id", item_a_id)
                .select("id")
                .execute()
                .data
            )
            assert deleted == [{"id": item_a_id}]
        if item_b_id is not None:
            deleted = (
                client_b.table("items")
                .delete()
                .eq("id", item_b_id)
                .select("id")
                .execute()
                .data
            )
            assert deleted == [{"id": item_b_id}]
        if forged_item_id is not None:
            deleted = (
                client_a.table("items")
                .delete()
                .eq("id", forged_item_id)
                .select("id")
                .execute()
                .data
            )
            assert deleted == [{"id": forged_item_id}]
