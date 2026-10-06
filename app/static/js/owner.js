/**
 * Staff/owner portal. Like the customer page, this only calls the
 * existing `/api/v1/owner/...` endpoints -- authorization, validation,
 * and Outlook writes remain entirely server-side.
 */
(() => {
  const errorBanner = document.getElementById("error-banner");
  const TOKEN_KEY = "windsor_owner_token";
  const SIGNED_IN_KEY = "windsor_ms_signed_in";

  function getToken() {
    return sessionStorage.getItem(TOKEN_KEY) || "";
  }

  /**
   * The real sign-in state lives in an httpOnly session cookie the server
   * sets, which JS cannot read directly. This sessionStorage flag is only
   * a cosmetic memory of "we were told sign-in succeeded" so the button
   * state survives a page reload; every actual request is still checked
   * server-side regardless of what the UI shows.
   */
  function refreshMicrosoftSignInUi() {
    const signedIn = sessionStorage.getItem(SIGNED_IN_KEY) === "1";
    document.getElementById("microsoft-signin-status").textContent = signedIn
      ? "Signed in with Microsoft."
      : "Not signed in.";
    document.getElementById("microsoft-signin-button").closest("a").hidden = signedIn;
    document.getElementById("microsoft-signout-form").hidden = !signedIn;
  }

  function handleMicrosoftAuthRedirect() {
    const params = new URLSearchParams(window.location.search);
    const auth = params.get("auth");
    if (!auth) return;

    if (auth === "success") {
      sessionStorage.setItem(SIGNED_IN_KEY, "1");
    } else if (auth === "forbidden") {
      sessionStorage.removeItem(SIGNED_IN_KEY);
      showApiError(errorBanner, {
        data: { error: { code: "FORBIDDEN", message: "That Microsoft account is not on the owner allow-list." } },
      });
    } else if (auth === "expired") {
      sessionStorage.removeItem(SIGNED_IN_KEY);
      showApiError(errorBanner, {
        data: { error: { code: "SIGN_IN_EXPIRED", message: "Sign-in took too long or was restarted. Please try again." } },
      });
    }

    params.delete("auth");
    const query = params.toString();
    window.history.replaceState({}, "", window.location.pathname + (query ? `?${query}` : ""));
  }

  function syncSignInUiWithResult(result) {
    // If the server says we're no longer authorized (cookie expired, or
    // the UPN was removed from the allow-list), stop showing a stale
    // "signed in" state -- regardless of which auth path was actually used.
    if (result.status === 401 || result.status === 403) {
      sessionStorage.removeItem(SIGNED_IN_KEY);
      refreshMicrosoftSignInUi();
    }
  }

  function handleSignOutSubmit(event) {
    event.preventDefault();
    sessionStorage.removeItem(SIGNED_IN_KEY);
    fetch("/auth/microsoft/logout", { method: "POST", credentials: "same-origin" }).finally(refreshMicrosoftSignInUi);
  }

  function refreshTokenStatus() {
    const status = document.getElementById("token-status");
    status.textContent = getToken()
      ? "Token saved for this browser session."
      : "No token saved for this browser session.";
  }

  function handleSaveToken() {
    const value = document.getElementById("owner-token").value.trim();
    if (value) sessionStorage.setItem(TOKEN_KEY, value);
    refreshTokenStatus();
  }

  function handleClearToken() {
    sessionStorage.removeItem(TOKEN_KEY);
    document.getElementById("owner-token").value = "";
    refreshTokenStatus();
  }

  function withSeconds(datetimeLocalValue) {
    // <input type="datetime-local"> yields "YYYY-MM-DDTHH:MM"; the API's
    // datetime fields parse most ISO 8601 variants, but we normalize to
    // include seconds for consistency with the rest of the API.
    if (!datetimeLocalValue) return datetimeLocalValue;
    return datetimeLocalValue.length === 16 ? `${datetimeLocalValue}:00` : datetimeLocalValue;
  }

  function formatDateTime(iso) {
    return formatShopTime(iso, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  }

  async function handleLoadSchedule() {
    hideApiError(errorBanner);
    const from = withSeconds(document.getElementById("schedule-from").value);
    const to = withSeconds(document.getElementById("schedule-to").value);
    if (!from || !to) {
      showApiError(errorBanner, {
        data: { error: { code: "VALIDATION_ERROR", message: "Choose both a from and to date/time." } },
      });
      return;
    }

    const result = await Api.get(
      `/api/v1/owner/appointments?date_from=${encodeURIComponent(from)}&date_to=${encodeURIComponent(to)}`,
      { authToken: getToken() },
    );
    syncSignInUiWithResult(result);
    if (!result.ok) {
      showApiError(errorBanner, result);
      return;
    }

    const appointments = result.data.appointments;
    const table = document.getElementById("schedule-table");
    const body = document.getElementById("schedule-body");
    const empty = document.getElementById("schedule-empty");
    body.innerHTML = "";

    if (appointments.length === 0) {
      table.hidden = true;
      empty.hidden = false;
      return;
    }
    empty.hidden = true;
    table.hidden = false;

    appointments.forEach((appt) => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${formatDateTime(appt.start)}</td>
        <td>${formatDateTime(appt.end)}</td>
        <td>${appt.subject}</td>
        <td>${appt.outlook_event_id}</td>
      `;
      body.appendChild(row);
    });
  }

  async function handleCreateBlock() {
    hideApiError(errorBanner);
    const start = withSeconds(document.getElementById("block-start").value);
    const end = withSeconds(document.getElementById("block-end").value);
    const reason = document.getElementById("block-reason").value.trim();
    const statusEl = document.getElementById("block-status");
    statusEl.textContent = "";

    if (!start || !end) {
      showApiError(errorBanner, {
        data: { error: { code: "VALIDATION_ERROR", message: "Choose both a start and end time." } },
      });
      return;
    }

    const result = await Api.post(
      "/api/v1/owner/blocks",
      { start, end, ...(reason ? { reason } : {}) },
      { authToken: getToken() },
    );
    syncSignInUiWithResult(result);
    if (!result.ok) {
      showApiError(errorBanner, result);
      return;
    }

    statusEl.textContent = `Block created (reference: ${result.data.block.outlook_event_id}).`;
  }

  async function loadAppointmentTypes() {
    const result = await Api.get("/api/v1/appointment-types");
    if (!result.ok) {
      showApiError(errorBanner, result);
      return;
    }
    renderTypes(result.data.appointment_types);
  }

  function renderTypes(types) {
    const container = document.getElementById("types-list");
    container.innerHTML = "";

    types.forEach((type) => {
      const row = document.createElement("div");
      row.className = "type-row";
      row.innerHTML = `
        <div class="field">
          <label>Type</label>
          <strong>${type.display_name}</strong>
        </div>
        <div class="field">
          <label>Duration (min)</label>
          <input type="number" min="5" max="480" value="${type.duration_minutes}" class="type-duration">
        </div>
        <div class="field">
          <label>Buffer (min)</label>
          <input type="number" min="0" max="120" value="${type.buffer_minutes}" class="type-buffer">
        </div>
        <div class="field">
          <label>Active</label>
          <input type="checkbox" class="type-active" ${type.active === false ? "" : "checked"}>
        </div>
        <button type="button" class="secondary type-save">Save</button>
      `;
      row.querySelector(".type-save").addEventListener("click", () => saveType(type.id, row));
      container.appendChild(row);
    });
  }

  async function saveType(typeId, row) {
    hideApiError(errorBanner);
    const payload = {
      duration_minutes: Number(row.querySelector(".type-duration").value),
      buffer_minutes: Number(row.querySelector(".type-buffer").value),
      active: row.querySelector(".type-active").checked,
    };

    const result = await Api.put(`/api/v1/owner/appointment-types/${typeId}`, payload, { authToken: getToken() });
    syncSignInUiWithResult(result);
    if (!result.ok) {
      showApiError(errorBanner, result);
      return;
    }
    // Re-render everything from the confirmed server state.
    loadAppointmentTypes();
  }

  document.getElementById("save-token-button").addEventListener("click", handleSaveToken);
  document.getElementById("clear-token-button").addEventListener("click", handleClearToken);
  document.getElementById("load-schedule-button").addEventListener("click", handleLoadSchedule);
  document.getElementById("create-block-button").addEventListener("click", handleCreateBlock);
  document.getElementById("microsoft-signout-form").addEventListener("submit", handleSignOutSubmit);

  handleMicrosoftAuthRedirect();
  refreshMicrosoftSignInUi();
  refreshTokenStatus();
  loadAppointmentTypes();
})();
