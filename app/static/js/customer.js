/**
 * Customer booking flow. Every scheduling decision (which slots are
 * offered, whether a slot is still free, whether a booking succeeds)
 * happens server-side via SchedulingOrchestrator/BusinessRulesService/
 * AvailabilityService/OutlookGateway. This file only calls the existing
 * `/api/v1/...` endpoints and renders their responses.
 */
(() => {
  const errorBanner = document.getElementById("error-banner");
  const intentHint = document.getElementById("intent-hint");

  const state = {
    appointmentTypes: [], // [{id, code, display_name, ...}]
    slots: [], // [{slot_id, start, end}]
    selectedSlot: null,
  };

  function setStep(stepNumber) {
    for (let i = 1; i <= 4; i += 1) {
      const el = document.getElementById(`step-${i}`);
      el.classList.remove("is-active", "is-done");
      if (i < stepNumber) el.classList.add("is-done");
      if (i === stepNumber) el.classList.add("is-active");
    }
  }

  function formatRange(startIso, endIso) {
    const dateFmt = { weekday: "short", month: "short", day: "numeric" };
    const timeFmt = { hour: "numeric", minute: "2-digit" };
    return `${formatShopTime(startIso, dateFmt)}, ${formatShopTime(startIso, timeFmt)} \u2013 ${formatShopTime(endIso, timeFmt)}`;
  }

  async function loadAppointmentTypes() {
    const result = await Api.get("/api/v1/appointment-types");
    if (!result.ok) {
      showApiError(errorBanner, result);
      return;
    }
    state.appointmentTypes = result.data.appointment_types;
    const select = document.getElementById("appointment-type");
    select.innerHTML = "";
    state.appointmentTypes.forEach((type) => {
      const option = document.createElement("option");
      option.value = type.code;
      option.textContent = `${type.display_name} (${type.duration_minutes} min)`;
      option.dataset.id = type.id;
      select.appendChild(option);
    });
  }

  function typeIdForCode(code) {
    const match = state.appointmentTypes.find((t) => t.code === code);
    return match ? match.id : null;
  }

  async function handleInterpret() {
    hideApiError(errorBanner);
    intentHint.textContent = "";
    const text = document.getElementById("intent-text").value.trim();
    if (!text) return;

    const result = await Api.post("/api/v1/intent", { text, actor: "customer" });
    if (!result.ok) {
      showApiError(errorBanner, result);
      return;
    }

    const { intent, needs_clarification, clarification_question } = result.data;
    if (needs_clarification) {
      intentHint.textContent = clarification_question || "Could you add a bit more detail?";
      return;
    }

    if (intent.appointment_type) {
      const select = document.getElementById("appointment-type");
      const optionExists = Array.from(select.options).some((o) => o.value === intent.appointment_type);
      if (optionExists) select.value = intent.appointment_type;
    }
    if (intent.date_start) document.getElementById("date-start").value = intent.date_start;
    if (intent.time_start) document.getElementById("time-start").value = intent.time_start.slice(0, 5);
    if (intent.time_end) document.getElementById("time-end").value = intent.time_end.slice(0, 5);
    intentHint.textContent = "Fields filled in below \u2014 adjust anything and search.";
  }

  async function handleSearch() {
    hideApiError(errorBanner);
    const date = document.getElementById("date-start").value;
    const appointmentType = document.getElementById("appointment-type").value;

    if (!date || !appointmentType) {
      showApiError(errorBanner, {
        data: { error: { code: "VALIDATION_ERROR", message: "Choose an appointment type and a date first." } },
      });
      return;
    }

    const payload = {
      appointment_type: appointmentType,
      date_start: date,
      date_end: date,
      max_options: 6,
    };
    const timeStart = document.getElementById("time-start").value;
    const timeEnd = document.getElementById("time-end").value;
    if (timeStart) payload.time_start = `${timeStart}:00`;
    if (timeEnd) payload.time_end = `${timeEnd}:00`;

    const result = await Api.post("/api/v1/availability", payload);
    if (!result.ok) {
      showApiError(errorBanner, result);
      return;
    }

    state.slots = result.data.options;
    renderSlots();
    document.getElementById("slots-section").hidden = false;
    document.getElementById("slots-section").scrollIntoView({ behavior: "smooth", block: "start" });
    setStep(2);
  }

  function renderSlots() {
    const grid = document.getElementById("slot-grid");
    const empty = document.getElementById("slots-empty");
    grid.innerHTML = "";

    if (state.slots.length === 0) {
      empty.hidden = false;
      return;
    }
    empty.hidden = true;

    state.slots.forEach((slot) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "slot-button";
      button.textContent = formatRange(slot.start, slot.end);
      button.addEventListener("click", () => selectSlot(slot, button));
      grid.appendChild(button);
    });
  }

  function selectSlot(slot, button) {
    state.selectedSlot = slot;
    document.querySelectorAll(".slot-button").forEach((b) => b.classList.remove("is-selected"));
    button.classList.add("is-selected");

    document.getElementById("selected-slot-label").textContent = formatRange(slot.start, slot.end);
    document.getElementById("details-section").hidden = false;
    document.getElementById("details-section").scrollIntoView({ behavior: "smooth", block: "start" });
    setStep(3);
  }

  async function handleConfirm() {
    hideApiError(errorBanner);
    const name = document.getElementById("customer-name").value.trim();
    const email = document.getElementById("customer-email").value.trim();
    const phone = document.getElementById("customer-phone").value.trim();
    const notes = document.getElementById("customer-notes").value.trim();

    if (!name || !email || !state.selectedSlot) {
      showApiError(errorBanner, {
        data: { error: { code: "VALIDATION_ERROR", message: "Name and email are required." } },
      });
      return;
    }

    const appointmentTypeId = typeIdForCode(document.getElementById("appointment-type").value);
    const payload = {
      customer: { name, email, ...(phone ? { phone } : {}) },
      appointment_type_id: appointmentTypeId,
      start: state.selectedSlot.start,
      confirmation: true,
      ...(notes ? { notes } : {}),
    };

    const result = await Api.post("/api/v1/appointments", payload);
    if (!result.ok) {
      showApiError(errorBanner, result);
      // On a slot conflict, the slot list is stale -- send them back to re-search.
      if (result.data && result.data.error && result.data.error.code === "SLOT_CONFLICT") {
        document.getElementById("details-section").hidden = true;
        document.getElementById("slots-section").scrollIntoView({ behavior: "smooth", block: "start" });
        setStep(2);
      }
      return;
    }

    const { appointment } = result.data;
    document.getElementById("confirmation-status").textContent = appointment.status;
    document.getElementById("confirmation-when").textContent = formatRange(appointment.start, appointment.end);
    document.getElementById("confirmation-event-id").textContent = appointment.outlook_event_id;

    document.getElementById("search-section").hidden = true;
    document.getElementById("slots-section").hidden = true;
    document.getElementById("details-section").hidden = true;
    document.getElementById("confirmation-section").hidden = false;
    document.getElementById("confirmation-section").scrollIntoView({ behavior: "smooth", block: "start" });
    setStep(4);
  }

  function handleBookAnother() {
    state.selectedSlot = null;
    state.slots = [];
    hideApiError(errorBanner);
    document.getElementById("customer-name").value = "";
    document.getElementById("customer-email").value = "";
    document.getElementById("customer-phone").value = "";
    document.getElementById("customer-notes").value = "";
    document.getElementById("intent-text").value = "";
    intentHint.textContent = "";

    document.getElementById("confirmation-section").hidden = true;
    document.getElementById("search-section").hidden = false;
    document.getElementById("slots-section").hidden = true;
    document.getElementById("details-section").hidden = true;
    window.scrollTo({ top: 0, behavior: "smooth" });
    setStep(1);
  }

  function handleBackToSlots() {
    document.getElementById("details-section").hidden = true;
    setStep(2);
  }

  document.getElementById("interpret-button").addEventListener("click", handleInterpret);
  document.getElementById("search-button").addEventListener("click", handleSearch);
  document.getElementById("confirm-button").addEventListener("click", handleConfirm);
  document.getElementById("back-to-slots-button").addEventListener("click", handleBackToSlots);
  document.getElementById("book-another-button").addEventListener("click", handleBookAnother);

  loadAppointmentTypes();
})();
