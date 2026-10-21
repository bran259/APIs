import logging
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def app_module():
    with patch.dict(
        os.environ,
        {
            "SUPABASE_URL": "https://unit-test.supabase.co",
            "SUPABASE_KEY": "unit-test-key",
            "CORS_ORIGINS": (
                "http://localhost:3000,http://localhost:5173"
                ",https://frontend.example.com"
            ),
        },
    ):
        with patch("supabase.create_client", return_value=MagicMock()):
            import main

    return main


def test_cors_allows_configured_frontend_origins(api):
    client, _ = api

    response = client.options(
        "/items/",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_rejects_unconfigured_origins(api):
    client, _ = api

    response = client.options(
        "/items/",
        headers={
            "Origin": "https://unapproved.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_cors_origins_are_loaded_from_environment(app_module):
    assert app_module.CORS_ORIGINS == [
        "http://localhost:3000",
        "http://localhost:5173",
        "https://frontend.example.com",
    ]


def test_openapi_documents_response_and_error_models(api):
    client, _ = api
    openapi = client.get("/openapi.json").json()

    patch_operation = openapi["paths"]["/items/{item_id}"]["patch"]
    assert patch_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"] == "#/components/schemas/ItemEnvelope"
    assert patch_operation["responses"]["422"]["content"]["application/json"][
        "schema"
    ]["$ref"] == "#/components/schemas/ErrorResponse"


@pytest.fixture
def api(app_module, monkeypatch):
    supabase = MagicMock()
    monkeypatch.setattr(app_module, "supabase", supabase)
    monkeypatch.setattr(
        app_module, "create_user_database_client", lambda token: supabase
    )
    return TestClient(app_module.app), supabase


def authenticate(supabase, user_id="user-123"):
    supabase.auth.get_user.return_value = SimpleNamespace(
        user=SimpleNamespace(id=user_id)
    )
    return {"Authorization": "Bearer test-access-token"}


def test_item_reads_require_authentication(api):
    client, supabase = api

    collection_response = client.get("/items/")
    single_item_response = client.get("/items/1")

    assert collection_response.status_code in (401, 403)
    assert single_item_response.status_code in (401, 403)
    assert "error" in collection_response.json()
    assert "error" in single_item_response.json()
    supabase.table.assert_not_called()


def test_user_database_client_uses_request_token(app_module, monkeypatch):
    user_client = MagicMock()
    create_client = MagicMock(return_value=user_client)
    monkeypatch.setattr(app_module, "create_client", create_client)

    result = app_module.create_user_database_client("request-access-token")

    assert result is user_client
    user_client.postgrest.auth.assert_called_once_with("request-access-token")
    options = create_client.call_args.kwargs["options"]
    assert options.auto_refresh_token is False
    assert options.persist_session is False


def test_read_all_items(api):
    client, supabase = api
    headers = authenticate(supabase)
    supabase.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value.data = [
        {"id": 1, "name": "Notebook"}
    ]

    response = client.get("/items/", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "id": 1,
                "name": "Notebook",
                "description": None,
                "created_at": None,
                "user_id": None,
            }
        ],
        "pagination": {"limit": 50, "offset": 0, "next_offset": None},
    }
    supabase.table.assert_called_once_with("items")
    supabase.table.return_value.select.return_value.eq.assert_called_once_with(
        "user_id", "user-123"
    )
    query = supabase.table.return_value.select.return_value.eq.return_value
    query.order.assert_called_once_with("id")
    query.order.return_value.range.assert_called_once_with(0, 50)


@pytest.mark.parametrize(
    ("query", "expected_status"),
    [
        ("limit=0", 422),
        ("limit=101", 422),
        ("offset=-1", 422),
    ],
)
def test_read_all_items_rejects_invalid_pagination(api, query, expected_status):
    client, supabase = api
    headers = authenticate(supabase)

    response = client.get(f"/items/?{query}", headers=headers)

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == "validation_error"
    supabase.table.assert_not_called()


def test_read_all_items_returns_requested_page(api):
    client, supabase = api
    headers = authenticate(supabase)
    supabase.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value.data = [
        {"id": 3, "name": "Third"},
        {"id": 4, "name": "Fourth"},
        {"id": 5, "name": "Fifth"},
    ]

    response = client.get("/items/?limit=2&offset=2", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "id": 3,
                "name": "Third",
                "description": None,
                "created_at": None,
                "user_id": None,
            },
            {
                "id": 4,
                "name": "Fourth",
                "description": None,
                "created_at": None,
                "user_id": None,
            },
        ],
        "pagination": {"limit": 2, "offset": 2, "next_offset": 4},
    }
    query = supabase.table.return_value.select.return_value.eq.return_value
    query.order.assert_called_once_with("id")
    query.order.return_value.range.assert_called_once_with(2, 4)


def test_read_all_items_hides_and_logs_database_errors(api, caplog):
    client, supabase = api
    headers = authenticate(supabase)
    supabase.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.side_effect = (
        RuntimeError("private database details")
    )

    with caplog.at_level(logging.ERROR):
        response = client.get("/items/", headers=headers)

    assert response.status_code == 503
    assert "private database details" not in response.text
    assert response.json() == {
        "error": {
            "code": "service_unavailable",
            "message": "The database service is temporarily unavailable.",
        }
    }
    assert "Database operation read_all_items failed" in caplog.text
    assert "private database details" in caplog.text


def test_database_conflict_returns_safe_conflict_response(api):
    client, supabase = api
    headers = authenticate(supabase)
    import main as app_module

    supabase.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.side_effect = (
        app_module.PostgrestAPIError(
            {
                "message": "private constraint details",
                "code": "23505",
            }
        )
    )

    response = client.get("/items/", headers=headers)

    assert response.status_code == 409
    assert "private constraint details" not in response.text
    assert response.json()["error"]["code"] == "conflict"


def test_login_invalid_credentials_are_safe(api):
    client, supabase = api
    import main as app_module

    supabase.auth.sign_in_with_password.side_effect = app_module.AuthError(
        "private auth details", "invalid_credentials"
    )

    response = client.post(
        "/auth/login",
        json={"email": "person@example.com", "password": "secure-pass"},
    )

    assert response.status_code == 401
    assert "private auth details" not in response.text
    assert response.json() == {
        "error": {"code": "unauthorized", "message": "Invalid email or password."}
    }


def test_unexpected_signup_error_is_safe_and_logged(api, caplog):
    client, supabase = api
    supabase.auth.sign_up.side_effect = RuntimeError("private auth details")

    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/auth/signup",
            json={"email": "person@example.com", "password": "secure-pass"},
        )

    assert response.status_code == 503
    assert "private auth details" not in response.text
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "Supabase operation signup failed" in caplog.text
    assert "private auth details" in caplog.text


def test_unexpected_token_validation_error_is_service_unavailable(api, caplog):
    client, supabase = api
    supabase.auth.get_user.side_effect = RuntimeError("private auth details")

    with caplog.at_level(logging.ERROR):
        response = client.get(
            "/items/",
            headers={"Authorization": "Bearer test-access-token"},
        )

    assert response.status_code == 503
    assert "private auth details" not in response.text
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "Supabase operation validate_token failed" in caplog.text


def test_read_user_items_filters_by_user_id(api):
    client, supabase = api
    user_id = "123e4567-e89b-12d3-a456-426614174000"
    headers = authenticate(supabase, user_id)
    supabase.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value.data = [
        {"id": 1, "user_id": user_id, "name": "Notebook"}
    ]

    response = client.get(f"/items/user/{user_id}", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "id": 1,
                "name": "Notebook",
                "description": None,
                "created_at": None,
                "user_id": user_id,
            }
        ],
        "pagination": {"limit": 50, "offset": 0, "next_offset": None},
    }
    supabase.table.return_value.select.return_value.eq.assert_called_once_with(
        "user_id", user_id
    )
    query = supabase.table.return_value.select.return_value.eq.return_value
    query.order.assert_called_once_with("id")
    query.order.return_value.range.assert_called_once_with(0, 50)


def test_read_user_items_returns_requested_page(api):
    client, supabase = api
    user_id = "123e4567-e89b-12d3-a456-426614174000"
    headers = authenticate(supabase, user_id)
    supabase.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value.data = [
        {"id": 3, "user_id": user_id, "name": "Third"},
        {"id": 4, "user_id": user_id, "name": "Fourth"},
        {"id": 5, "user_id": user_id, "name": "Fifth"},
    ]

    response = client.get(
        f"/items/user/{user_id}?limit=2&offset=2",
        headers=headers,
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [3, 4]
    assert response.json()["pagination"] == {
        "limit": 2,
        "offset": 2,
        "next_offset": 4,
    }
    query = supabase.table.return_value.select.return_value.eq.return_value
    query.order.assert_called_once_with("id")
    query.order.return_value.range.assert_called_once_with(2, 4)


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_read_user_items_rejects_invalid_pagination(api, query):
    client, supabase = api
    user_id = "123e4567-e89b-12d3-a456-426614174000"
    headers = authenticate(supabase, user_id)

    response = client.get(f"/items/user/{user_id}?{query}", headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    supabase.table.assert_not_called()


def test_read_user_items_rejects_another_users_id(api):
    client, supabase = api
    headers = authenticate(supabase)

    response = client.get(
        "/items/user/123e4567-e89b-12d3-a456-426614174000",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    supabase.table.assert_not_called()


def test_read_user_items_rejects_invalid_user_id(api):
    client, supabase = api
    headers = authenticate(supabase)

    response = client.get("/items/user/not-a-uuid", headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    supabase.table.assert_not_called()


def test_read_single_item(api):
    client, supabase = api
    headers = authenticate(supabase)
    item_id = 2
    supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"id": item_id, "name": "Notebook"}
    ]

    response = client.get(f"/items/{item_id}", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "id": item_id,
            "name": "Notebook",
            "description": None,
            "created_at": None,
            "user_id": None,
        }
    }
    supabase.table.return_value.select.return_value.eq.assert_called_once_with(
        "id", item_id
    )
    supabase.table.return_value.select.return_value.eq.return_value.eq.assert_called_once_with(
        "user_id", "user-123"
    )


def test_read_single_item_returns_404_when_missing(api):
    client, supabase = api
    headers = authenticate(supabase)
    item_id = 2
    supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    response = client.get(f"/items/{item_id}", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_read_single_item_rejects_non_integer_id(api):
    client, supabase = api
    headers = authenticate(supabase)

    response = client.get("/items/not-an-integer", headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    supabase.table.assert_not_called()


def test_sign_up(api):
    client, supabase = api
    supabase.auth.sign_up.return_value = SimpleNamespace(
        user=SimpleNamespace(id="user-123")
    )

    response = client.post(
        "/auth/signup",
        json={"email": "person@example.com", "password": "secure-pass"},
    )

    assert response.status_code == 201
    assert response.json()["user_id"] == "user-123"
    supabase.auth.sign_up.assert_called_once_with(
        {"email": "person@example.com", "password": "secure-pass"}
    )


@pytest.mark.parametrize(
    "auth_response",
    [
        SimpleNamespace(user=None),
        SimpleNamespace(user=SimpleNamespace(id=None)),
        SimpleNamespace(user=SimpleNamespace(id="")),
    ],
)
def test_sign_up_rejects_incomplete_auth_responses(api, caplog, auth_response):
    client, supabase = api
    supabase.auth.sign_up.return_value = auth_response

    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/auth/signup",
            json={"email": "person@example.com", "password": "secure-pass"},
        )

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "bad_gateway",
            "message": "The authentication service returned an invalid response.",
        }
    }
    assert "Supabase returned an incomplete response for signup" in caplog.text


def test_sign_up_rejects_invalid_email(api):
    client, supabase = api

    response = client.post(
        "/auth/signup",
        json={"email": "not-an-email", "password": "secure-pass"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    supabase.auth.sign_up.assert_not_called()


def test_login(api):
    client, supabase = api
    supabase.auth.sign_in_with_password.return_value = SimpleNamespace(
        session=SimpleNamespace(access_token="test-access-token"),
        user=SimpleNamespace(id="user-123"),
    )

    response = client.post(
        "/auth/login",
        json={"email": "person@example.com", "password": "secure-pass"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "test-access-token",
        "token_type": "bearer",
        "user_id": "user-123",
    }


@pytest.mark.parametrize(
    "auth_response",
    [
        SimpleNamespace(session=None, user=SimpleNamespace(id="user-123")),
        SimpleNamespace(
            session=SimpleNamespace(access_token="token"),
            user=None,
        ),
        SimpleNamespace(
            session=SimpleNamespace(access_token=""),
            user=SimpleNamespace(id="user-123"),
        ),
        SimpleNamespace(
            session=SimpleNamespace(access_token="token"),
            user=SimpleNamespace(id=""),
        ),
    ],
)
def test_login_rejects_incomplete_auth_responses(api, caplog, auth_response):
    client, supabase = api
    supabase.auth.sign_in_with_password.return_value = auth_response

    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/auth/login",
            json={"email": "person@example.com", "password": "secure-pass"},
        )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "bad_gateway"
    assert (
        "Supabase returned an incomplete response for login"
        in caplog.text
    )


def test_create_item_requires_authentication(api):
    client, supabase = api

    response = client.post("/items/", json={"name": "Notebook"})

    assert response.status_code in (401, 403)
    supabase.table.assert_not_called()


def test_create_item_assigns_authenticated_owner(api):
    client, supabase = api
    user_id = "user-123"
    supabase.auth.get_user.return_value = SimpleNamespace(
        user=SimpleNamespace(id=user_id)
    )
    supabase.table.return_value.insert.return_value.execute.return_value.data = [
        {
            "id": 3,
            "name": "Notebook",
            "description": "Notes",
            "user_id": user_id,
        }
    ]

    response = client.post(
        "/items/",
        headers={"Authorization": "Bearer valid-token"},
        json={"name": "Notebook", "description": "Notes"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "data": {
            "id": 3,
            "name": "Notebook",
            "description": "Notes",
            "created_at": None,
            "user_id": user_id,
        }
    }
    supabase.table.return_value.insert.assert_called_once_with(
        {"name": "Notebook", "description": "Notes", "user_id": user_id}
    )


def test_create_item_rejects_invalid_token(api):
    client, supabase = api
    import main as app_module

    supabase.auth.get_user.side_effect = app_module.AuthError(
        "private token details", "invalid_jwt"
    )

    response = client.post(
        "/items/",
        headers={"Authorization": "Bearer invalid-token"},
        json={"name": "Notebook"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    supabase.table.assert_not_called()


def test_create_item_rejects_invalid_payload(api):
    client, supabase = api
    supabase.auth.get_user.return_value = SimpleNamespace(
        user=SimpleNamespace(id="user-123")
    )

    response = client.post(
        "/items/",
        headers={"Authorization": "Bearer valid-token"},
        json={"name": ""},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    supabase.table.assert_not_called()


@pytest.mark.parametrize("name", [" ", "   ", "\t\n"])
def test_create_item_rejects_whitespace_only_name(api, name):
    client, supabase = api
    headers = authenticate(supabase)

    response = client.post(
        "/items/",
        headers=headers,
        json={"name": name},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    supabase.table.assert_not_called()


def test_create_item_trims_name(api):
    client, supabase = api
    headers = authenticate(supabase)
    supabase.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": 3, "name": "Notebook", "user_id": "user-123"}
    ]

    response = client.post(
        "/items/",
        headers=headers,
        json={"name": "  Notebook  "},
    )

    assert response.status_code == 201
    supabase.table.return_value.insert.assert_called_once_with(
        {"name": "Notebook", "description": None, "user_id": "user-123"}
    )


def test_update_item_only_targets_authenticated_owner(api):
    client, supabase = api
    user_id = "user-123"
    item_id = 3
    supabase.auth.get_user.return_value = SimpleNamespace(
        user=SimpleNamespace(id=user_id)
    )
    supabase.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"id": item_id, "name": "Updated", "user_id": user_id, "description": None}
    ]

    response = client.put(
        f"/items/{item_id}",
        headers={"Authorization": "Bearer valid-token"},
        json={"name": "Updated", "description": None},
    )

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Updated"
    assert response.json()["data"]["user_id"] == user_id
    first_filter = supabase.table.return_value.update.return_value.eq
    supabase.table.return_value.update.assert_called_once_with(
        {"name": "Updated", "description": None}
    )
    first_filter.assert_called_once_with("id", item_id)
    first_filter.return_value.eq.assert_called_once_with("user_id", user_id)


def test_put_item_rejects_whitespace_only_name(api):
    client, supabase = api
    headers = authenticate(supabase)

    response = client.put(
        "/items/3",
        headers=headers,
        json={"name": "   "},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    supabase.table.assert_not_called()


def test_patch_item_updates_only_provided_fields(api):
    client, supabase = api
    user_id = "user-123"
    item_id = 8
    headers = authenticate(supabase, user_id)
    supabase.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"id": item_id, "name": "Renamed", "user_id": user_id}
    ]

    response = client.patch(
        f"/items/{item_id}",
        headers=headers,
        json={"name": "Renamed"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["id"] == item_id
    assert response.json()["data"]["name"] == "Renamed"
    supabase.table.return_value.update.assert_called_once_with({"name": "Renamed"})
    filters = supabase.table.return_value.update.return_value.eq
    filters.assert_called_once_with("id", item_id)
    filters.return_value.eq.assert_called_once_with("user_id", user_id)


@pytest.mark.parametrize(
    "payload", [{}, {"name": None}, {"name": ""}, {"name": "   "}]
)
def test_patch_item_rejects_empty_or_invalid_patch(api, payload):
    client, supabase = api
    headers = authenticate(supabase)

    response = client.patch("/items/8", headers=headers, json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    supabase.table.assert_not_called()


def test_delete_item_only_targets_authenticated_owner(api):
    client, supabase = api
    user_id = "user-123"
    item_id = 4
    supabase.auth.get_user.return_value = SimpleNamespace(
        user=SimpleNamespace(id=user_id)
    )
    supabase.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"id": item_id, "name": "Notebook", "user_id": user_id}
    ]

    response = client.delete(
        f"/items/{item_id}",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["id"] == item_id
    first_filter = supabase.table.return_value.delete.return_value.eq
    first_filter.assert_called_once_with("id", item_id)
    first_filter.return_value.eq.assert_called_once_with("user_id", user_id)
