/**
 * Thin fetch wrapper shared by the customer and owner pages.
 *
 * This file contains no scheduling/business logic of any kind -- it only
 * calls the existing Flask API (`/api/v1/...`) and normalizes the
 * response. Every business rule, validation, and Outlook decision still
 * happens server-side in SchedulingOrchestrator/BusinessRulesService/
 * AvailabilityService/OutlookGateway, exactly as in Week 5.
 */
const Api = (() => {
  /**
   * @param {string} path e.g. "/api/v1/appointments"
   * @param {object} [options]
   * @param {string} [options.method]
   * @param {object} [options.body]
   * @param {string} [options.authToken] Owner bearer token, if required.
   * @returns {Promise<{ok: boolean, status: number, data: any}>}
   */
  async function call(path, options = {}) {
    const headers = { "Content-Type": "application/json" };
    if (options.authToken) {
      headers.Authorization = `Bearer ${options.authToken}`;
    }

    let response;
    try {
      response = await fetch(path, {
        method: options.method || "GET",
        headers,
        // Explicit, not just relying on the default: owner requests rely on
        // the session cookie set by /auth/microsoft/callback when signed in
        // with Microsoft, alongside (or instead of) the authToken header.
        credentials: "same-origin",
        body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      });
    } catch (networkError) {
      // The server is unreachable -- not an API error response at all.
      return {
        ok: false,
        status: 0,
        data: {
          error: {
            code: "NETWORK_ERROR",
            message: "Could not reach the server. Check your connection and try again.",
            retryable: true,
            request_id: null,
          },
        },
      };
    }

    let data = null;
    try {
      data = await response.json();
    } catch (parseError) {
      data = null;
    }

    return { ok: response.ok, status: response.status, data };
  }

  return {
    get: (path, options) => call(path, { ...options, method: "GET" }),
    post: (path, body, options) => call(path, { ...options, method: "POST", body }),
    put: (path, body, options) => call(path, { ...options, method: "PUT", body }),
  };
})();

/**
 * Renders the API's standard `{"error": {code, message, retryable,
 * request_id}}` contract into a page's error banner element. Works for
 * any endpoint since every route uses the same contract.
 */
function showApiError(bannerEl, result) {
  const error = result.data && result.data.error;
  const message = error ? error.message : "Something went wrong. Please try again.";
  const code = error ? error.code : "UNKNOWN_ERROR";
  const requestId = error ? error.request_id : null;

  bannerEl.innerHTML = "";

  const strong = document.createElement("strong");
  strong.textContent = code.replace(/_/g, " ");
  bannerEl.appendChild(strong);

  const text = document.createElement("span");
  text.textContent = message;
  bannerEl.appendChild(text);

  if (requestId) {
    const idLine = document.createElement("span");
    idLine.className = "request-id";
    idLine.textContent = `Reference: ${requestId}`;
    bannerEl.appendChild(idLine);
  }

  bannerEl.classList.add("is-visible");
}

function hideApiError(bannerEl) {
  bannerEl.classList.remove("is-visible");
  bannerEl.innerHTML = "";
}

/**
 * API datetimes are ISO 8601 strings carrying the shop's UTC offset, for
 * example "2026-09-29T09:00:00-05:00". Appointments happen at the shop, so
 * show the wall-clock time exactly as written instead of converting it to
 * the viewer's own timezone.
 */
function formatShopTime(iso, options) {
  const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso);
  if (!parts) return iso;
  const [year, month, day, hour, minute] = parts.slice(1).map(Number);
  const wallClock = new Date(Date.UTC(year, month - 1, day, hour, minute));
  return wallClock.toLocaleString(undefined, { ...options, timeZone: "UTC" });
}
