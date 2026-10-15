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
    assert response.json() == [{"id": 1, "name": "Notebook"}]
    supabase.table.assert_called_once_with("items")
    supabase.table.return_value.select.return_value.eq.assert_called_once_with(
        "user_id", "user-123"
    )
    query = supabase.table.return_value.select.return_value.eq.return_value
    query.order.assert_called_once_with("id")
    query.order.return_value.range.assert_called_once_with(0, 49)


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
    supabase.table.assert_not_called()


def test_read_all_items_returns_requested_page(api):
    client, supabase = api
    headers = authenticate(supabase)
    supabase.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value.data = [
        {"id": 3, "name": "Third"},
        {"id": 4, "name": "Fourth"},
    ]

    response = client.get("/items/?limit=2&offset=2", headers=headers)

    assert response.status_code == 200
    assert response.json() == [
        {"id": 3, "name": "Third"},
        {"id": 4, "name": "Fourth"},
    ]
    query = supabase.table.return_value.select.return_value.eq.return_value
    query.order.assert_called_once_with("id")
    query.order.return_value.range.assert_called_once_with(2, 3)


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
    assert response.json()["detail"] == "Invalid email or password."


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
    assert "Supabase operation validate_token failed" in caplog.text


def test_read_user_items_filters_by_user_id(api):
    client, supabase = api
    user_id = "123e4567-e89b-12d3-a456-426614174000"
    headers = authenticate(supabase, user_id)
    supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": 1, "user_id": user_id, "name": "Notebook"}
    ]

    response = client.get(f"/items/user/{user_id}", headers=headers)

    assert response.status_code == 200
    assert response.json()[0]["user_id"] == user_id
    supabase.table.return_value.select.return_value.eq.assert_called_once_with(
        "user_id", user_id
    )


def test_read_user_items_rejects_another_users_id(api):
    client, supabase = api
    headers = authenticate(supabase)

    response = client.get(
        "/items/user/123e4567-e89b-12d3-a456-426614174000",
        headers=headers,
    )

    assert response.status_code == 404
    supabase.table.assert_not_called()


def test_read_user_items_rejects_invalid_user_id(api):
    client, supabase = api
    headers = authenticate(supabase)

    response = client.get("/items/user/not-a-uuid", headers=headers)

    assert response.status_code == 422
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
    assert response.json() == {"id": item_id, "name": "Notebook"}
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


def test_read_single_item_rejects_non_integer_id(api):
    client, supabase = api
    headers = authenticate(supabase)

    response = client.get("/items/not-an-integer", headers=headers)

    assert response.status_code == 422
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


def test_sign_up_rejects_invalid_email(api):
    client, supabase = api

    response = client.post(
        "/auth/signup",
        json={"email": "not-an-email", "password": "secure-pass"},
    )

    assert response.status_code == 422
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
        {"id": 3, "name": "Notebook", "user_id": user_id}
    ]

    response = client.post(
        "/items/",
        headers={"Authorization": "Bearer valid-token"},
        json={"name": "Notebook", "description": "Notes"},
    )

    assert response.status_code == 201
    assert response.json()["author_id"] == user_id
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
    supabase.table.assert_not_called()


def test_update_item_only_targets_authenticated_owner(api):
    client, supabase = api
    user_id = "user-123"
    item_id = 3
    supabase.auth.get_user.return_value = SimpleNamespace(
        user=SimpleNamespace(id=user_id)
    )
    supabase.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"id": item_id, "name": "Updated", "user_id": user_id}
    ]

    response = client.put(
        f"/items/{item_id}",
        headers={"Authorization": "Bearer valid-token"},
        json={"name": "Updated"},
    )

    assert response.status_code == 200
    first_filter = supabase.table.return_value.update.return_value.eq
    first_filter.assert_called_once_with("id", item_id)
    first_filter.return_value.eq.assert_called_once_with("user_id", user_id)


def test_delete_item_only_targets_authenticated_owner(api):
    client, supabase = api
    user_id = "user-123"
    item_id = 4
    supabase.auth.get_user.return_value = SimpleNamespace(
        user=SimpleNamespace(id=user_id)
    )
    supabase.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"id": item_id, "user_id": user_id}
    ]

    response = client.delete(
        f"/items/{item_id}",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200
    first_filter = supabase.table.return_value.delete.return_value.eq
    first_filter.assert_called_once_with("id", item_id)
    first_filter.return_value.eq.assert_called_once_with("user_id", user_id)
