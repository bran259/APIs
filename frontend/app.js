const PAGE_SIZE = 10;
const AUTH_TOKEN_KEY = "things.accessToken";
const USER_EMAIL_KEY = "things.userEmail";
const API_TIMEOUT_MS = 15000;
const SLOW_AUTH_REQUEST_MS = 5000;

const state = {
  mode: "login",
  offset: 0,
  nextOffset: null,
  itemCount: 0,
  busy: false,
  loading: false,
};

const $ = (selector) => document.querySelector(selector);

const authView = $("#auth-view");
const workspaceView = $("#workspace-view");
const authForm = $("#auth-form");
const authMessage = $("#auth-message");
const workspaceMessage = $("#workspace-message");
const editMessage = $("#edit-message");
const itemForm = $("#item-form");
const itemList = $("#item-list");
const itemsLoading = $("#items-loading");
const itemsEmpty = $("#items-empty");
const editDialog = $("#edit-dialog");

function token() {
  return sessionStorage.getItem(AUTH_TOKEN_KEY);
}

function setNotice(element, message = "", isError = false) {
  element.textContent = message;
  element.hidden = !message;
  element.classList.toggle("is-error", Boolean(message) && isError);
}

function setBusy(button, busy, label) {
  const wasDisabled = button.disabled;
  button.disabled = busy;
  const text = button.querySelector("span");
  if (busy) {
    if (!wasDisabled) button.dataset.idleLabel = text?.textContent ?? button.textContent;
    if (text) text.textContent = label;
    else button.textContent = label;
  } else {
    if (text) text.textContent = button.dataset.idleLabel || text.textContent;
    else button.textContent = button.dataset.idleLabel || button.textContent;
  }
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers);
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (token()) headers.set("Authorization", `Bearer ${token()}`);

  let response;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    response = await fetch(path, { ...options, headers, signal: controller.signal });
  } catch {
    if (controller.signal.aborted) {
      throw new Error(
        "The service took too long to respond. Check that the API and Supabase are available, then try again.",
      );
    }
    throw new Error("Could not reach the service. Check your connection and try again.");
  } finally {
    window.clearTimeout(timeoutId);
  }

  const body = await response.json().catch(() => null);
  if (response.status === 401 && path !== "/auth/login" && path !== "/auth/signup") {
    logout(false);
    setNotice(authMessage, "Your session has expired. Please sign in again.", true);
    throw new Error("Your session has expired. Please sign in again.");
  }
  if (!response.ok) {
    throw new Error(body?.error?.message || "Something went wrong. Please try again.");
  }
  return body;
}

function setMode(mode) {
  state.mode = mode;
  const signingUp = mode === "signup";
  $("#login-tab").classList.toggle("is-active", !signingUp);
  $("#signup-tab").classList.toggle("is-active", signingUp);
  $("#login-tab").setAttribute("aria-selected", String(!signingUp));
  $("#signup-tab").setAttribute("aria-selected", String(signingUp));
  $("#auth-title").textContent = signingUp ? "Let’s get started." : "Good to have you.";
  $("#auth-subtitle").textContent = signingUp
    ? "Create your space. It only takes a moment."
    : "Sign in to pick up where you left off.";
  const submitLabel = signingUp ? "Create my account" : "Sign in";
  $("#auth-submit").querySelector("span").textContent = submitLabel;
  if ($("#auth-submit").disabled) $("#auth-submit").dataset.idleLabel = submitLabel;
  $("#auth-password").autocomplete = signingUp ? "new-password" : "current-password";
  $("#auth-password").minLength = signingUp ? 12 : 6;
  $("#auth-password").placeholder = signingUp ? "12 characters or more" : "Your account password";
  $("#password-hint").textContent = signingUp
    ? "Choose at least 12 characters."
    : "Use your account password.";
  setNotice(authMessage);
}

function showWorkspace() {
  authView.hidden = true;
  workspaceView.hidden = false;
  $("#account-actions").hidden = false;
  $("#account-email").textContent = sessionStorage.getItem(USER_EMAIL_KEY) || "";
  $("#today-label").textContent = new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(new Date());
  loadItems();
}

function logout(showMessage = true) {
  sessionStorage.removeItem(AUTH_TOKEN_KEY);
  sessionStorage.removeItem(USER_EMAIL_KEY);
  workspaceView.hidden = true;
  $("#account-actions").hidden = true;
  authView.hidden = false;
  state.offset = 0;
  state.nextOffset = null;
  itemList.replaceChildren();
  $("#item-count").textContent = "0";
  if (showMessage) setNotice(authMessage, "You’re signed out. See you next time.");
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(date);
}

function renderItems(items) {
  itemList.replaceChildren();
  for (const [index, item] of items.entries()) {
    const card = document.createElement("article");
    card.className = "item-card";
    card.style.animationDelay = `${Math.min(index * 35, 210)}ms`;

    const icon = document.createElement("span");
    icon.className = "item-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "✳";

    const copy = document.createElement("div");
    copy.className = "item-copy";
    const title = document.createElement("h3");
    title.className = "item-title";
    title.textContent = item.name;
    copy.append(title);

    if (item.description) {
      const description = document.createElement("p");
      description.className = "item-description";
      description.textContent = item.description;
      copy.append(description);
    }
    const dateText = formatDate(item.created_at);
    if (dateText) {
      const date = document.createElement("time");
      date.className = "item-date";
      date.dateTime = item.created_at;
      date.textContent = `Added ${dateText}`;
      copy.append(date);
    }

    const actions = document.createElement("div");
    actions.className = "item-actions";
    const editButton = document.createElement("button");
    editButton.className = "icon-button";
    editButton.type = "button";
    editButton.setAttribute("aria-label", `Edit ${item.name}`);
    editButton.title = "Edit";
    editButton.textContent = "↗";
    editButton.addEventListener("click", () => openEditor(item));
    const deleteButton = document.createElement("button");
    deleteButton.className = "icon-button delete-button";
    deleteButton.type = "button";
    deleteButton.setAttribute("aria-label", `Delete ${item.name}`);
    deleteButton.title = "Delete";
    deleteButton.textContent = "×";
    deleteButton.addEventListener("click", () => deleteItem(item));
    actions.append(editButton, deleteButton);
    card.append(icon, copy, actions);
    itemList.append(card);
  }
}

async function loadItems() {
  if (!token() || state.loading) return;
  state.loading = true;
  itemsLoading.hidden = false;
  itemsEmpty.hidden = true;
  itemList.replaceChildren();
  $("#previous-page").disabled = true;
  $("#next-page").disabled = true;
  setNotice(workspaceMessage);
  try {
    const result = await api(`/items/?limit=${PAGE_SIZE}&offset=${state.offset}`);
    renderItems(result.data);
    state.nextOffset = result.pagination.next_offset;
    state.itemCount = result.data.length;
    $("#item-count").textContent = String(state.itemCount);
    $("#page-label").textContent = result.data.length
      ? `Showing ${state.offset + 1}–${state.offset + result.data.length}`
      : "Your collection";
    itemsEmpty.hidden = result.data.length !== 0 || state.offset !== 0;
    $("#previous-page").disabled = state.offset === 0;
    $("#next-page").disabled = state.nextOffset === null;
  } catch (error) {
    setNotice(workspaceMessage, error.message, true);
    $("#page-label").textContent = "Couldn’t load your collection";
  } finally {
    state.loading = false;
    itemsLoading.hidden = true;
  }
}

function openEditor(item) {
  $("#edit-id").value = item.id;
  $("#edit-name").value = item.name;
  $("#edit-description").value = item.description || "";
  setNotice(workspaceMessage);
  setNotice(editMessage);
  editDialog.showModal();
  $("#edit-name").focus();
}

async function deleteItem(item) {
  if (!window.confirm(`Delete “${item.name}”? This can’t be undone.`)) return;
  try {
    await api(`/items/${item.id}`, { method: "DELETE" });
    if (state.offset > 0 && state.itemCount === 1) state.offset = Math.max(0, state.offset - PAGE_SIZE);
    await loadItems();
    setNotice(workspaceMessage, "That thing has been removed.");
  } catch (error) {
    setNotice(workspaceMessage, error.message, true);
  }
}

$("#login-tab").addEventListener("click", () => setMode("login"));
$("#signup-tab").addEventListener("click", () => setMode("signup"));

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  const button = $("#auth-submit");
  const email = $("#auth-email").value.trim();
  const password = $("#auth-password").value;
  const signup = state.mode === "signup";
  state.busy = true;
  setBusy(button, true, signup ? "Creating your account..." : "Signing in...");
  const slowRequestTimer = window.setTimeout(() => {
    if (state.busy) setBusy(button, true, "Still waiting for Supabase...");
  }, SLOW_AUTH_REQUEST_MS);
  setNotice(authMessage);
  try {
    if (signup) {
      const result = await api("/auth/signup", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setMode("login");
      $("#auth-email").value = email;
      $("#auth-password").value = "";
      setNotice(authMessage, `${result.message} After confirming, come back here to sign in.`);
    } else {
      const result = await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      sessionStorage.setItem(AUTH_TOKEN_KEY, result.access_token);
      sessionStorage.setItem(USER_EMAIL_KEY, email);
      authForm.reset();
      showWorkspace();
    }
  } catch (error) {
    setNotice(authMessage, error.message, true);
  } finally {
    window.clearTimeout(slowRequestTimer);
    state.busy = false;
    setBusy(button, false);
  }
});

itemForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#item-submit");
  setBusy(button, true, "Adding...");
  setNotice(workspaceMessage);
  try {
    await api("/items/", {
      method: "POST",
      body: JSON.stringify({
        name: $("#item-name").value.trim(),
        description: $("#item-description").value.trim() || null,
      }),
    });
    itemForm.reset();
    state.offset = 0;
    await loadItems();
    setNotice(workspaceMessage, "Added to your things. Nice.");
    $("#item-name").focus();
  } catch (error) {
    setNotice(workspaceMessage, error.message, true);
  } finally {
    setBusy(button, false);
  }
});

$("#edit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#save-edit");
  setBusy(button, true, "Saving...");
  try {
    await api(`/items/${$("#edit-id").value}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: $("#edit-name").value.trim(),
        description: $("#edit-description").value.trim() || null,
      }),
    });
    editDialog.close();
    await loadItems();
    setNotice(workspaceMessage, "Your changes are saved.");
  } catch (error) {
    setNotice(editMessage, error.message, true);
  } finally {
    setBusy(button, false);
  }
});

$("#close-dialog").addEventListener("click", () => editDialog.close());
$("#cancel-edit").addEventListener("click", () => editDialog.close());
editDialog.addEventListener("click", (event) => {
  if (event.target === editDialog) editDialog.close();
});
$("#logout-button").addEventListener("click", () => logout());
$("#refresh-button").addEventListener("click", loadItems);
$("#previous-page").addEventListener("click", () => {
  state.offset = Math.max(0, state.offset - PAGE_SIZE);
  loadItems();
});
$("#next-page").addEventListener("click", () => {
  if (state.nextOffset !== null) {
    state.offset = state.nextOffset;
    loadItems();
  }
});

if (token()) {
  showWorkspace();
} else {
  setMode("login");
}
