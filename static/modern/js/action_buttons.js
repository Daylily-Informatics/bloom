/* Modern action form helpers backed by TapDB-pattern execution. */

function sanitizeIdSegment(value) {
  return String(value || "").replace(/[^a-zA-Z0-9_-]/g, "_");
}

function getActionFormId(stepEuid, actionName, actionGroup) {
  return (
    "action-form-" +
    sanitizeIdSegment(stepEuid) +
    "-" +
    sanitizeIdSegment(actionGroup) +
    "-" +
    sanitizeIdSegment(actionName)
  );
}

function normalizeOptions(options) {
  if (!Array.isArray(options)) return [];
  return options
    .map((opt) => {
      if (!opt || typeof opt !== "object") return null;
      const value = String(opt.value || "").trim();
      if (!value) return null;
      return { value, label: String(opt.label || value).trim() };
    })
    .filter((opt) => opt !== null);
}

async function fetchWorkflowAssayOptions() {
  const response = await fetch("/api/v1/objects/?category=workflow&type=assay&page_size=1000");
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    return [];
  }
  const items = Array.isArray(payload.items) ? payload.items : [];
  return items
    .filter((item) => item && item.euid)
    .map((item) => ({
      value: String(item.euid),
      label: `${String(item.name || item.euid)} [${String(item.euid)}]`,
    }));
}

async function resolveFieldOptions(field) {
  const direct = normalizeOptions(field.options);
  if (direct.length > 0) return direct;
  if (field.options_source === "workflow_assays") return fetchWorkflowAssayOptions();
  return [];
}

function createFieldInput(field, options) {
  const type = String(field.type || "text").toLowerCase();
  let input;

  if (type === "textarea") {
    input = document.createElement("textarea");
    input.rows = Number(field.rows || 4);
  } else if (type === "select") {
    input = document.createElement("select");
    const selectOptions = normalizeOptions(options || []);
    if (selectOptions.length === 0) {
      const emptyOption = document.createElement("option");
      emptyOption.value = "";
      emptyOption.textContent = field.placeholder || "No options available";
      emptyOption.selected = true;
      input.appendChild(emptyOption);
    } else {
      for (const opt of selectOptions) {
        const option = document.createElement("option");
        option.value = opt.value;
        option.textContent = opt.label;
        input.appendChild(option);
      }
    }
  } else {
    input = document.createElement("input");
    input.type = type === "number" ? "number" : type === "file" ? "file" : "text";
    if (type === "number") {
      if (field.min !== undefined) input.min = String(field.min);
      if (field.max !== undefined) input.max = String(field.max);
      if (field.step !== undefined) input.step = String(field.step);
    }
    if (type === "file") {
      if (field.accept) input.accept = String(field.accept);
      if (field.multiple === true) input.multiple = true;
    }
  }

  input.name = String(field.name || "").trim();
  input.required = !!field.required;
  input.className = "action-field-input";
  input.setAttribute("data-testid", `action-field-${sanitizeIdSegment(input.name)}`);
  if (type !== "file" && field.default !== undefined && field.default !== null) {
    input.value = String(field.default);
  }
  return input;
}

async function readFileAsText(file) {
  if (!file) return "";
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result || "");
    reader.onerror = () => reject(reader.error || new Error("Unable to read selected file"));
    reader.readAsText(file);
  });
}

async function buildCapturedDataFromForm(form) {
  const formData = new FormData(form);
  const capturedData = {};
  for (const [key, value] of formData.entries()) {
    if (value instanceof File) {
      if (!value.name || value.size === 0) continue;
      const fileText = await readFileAsText(value);
      capturedData[key] = fileText;
      capturedData[`${key}_name`] = value.name;
      capturedData[`${key}_text`] = fileText;
      continue;
    }
    if (Object.prototype.hasOwnProperty.call(capturedData, key)) {
      if (Array.isArray(capturedData[key])) capturedData[key].push(value);
      else capturedData[key] = [capturedData[key], value];
    } else {
      capturedData[key] = value;
    }
  }
  return capturedData;
}

async function performUiAction(payload) {
  const response = await fetch("/ui/actions/execute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  let parsed = {};
  try {
    parsed = await response.json();
  } catch {
    parsed = {};
  }

  if (response.ok) return parsed;

  const detail = parsed && parsed.detail ? parsed.detail : {};
  const message =
    (typeof detail === "string" && detail) ||
    detail.message ||
    parsed.message ||
    "Action failed";
  const err = new Error(message);
  err.error_fields = Array.isArray(detail.error_fields)
    ? detail.error_fields
    : Array.isArray(parsed.error_fields)
      ? parsed.error_fields
      : [];
  throw err;
}

function clearFieldErrors(form) {
  for (const el of form.querySelectorAll("[data-action-field-error='1']")) {
    el.removeAttribute("data-action-field-error");
    el.style.borderColor = "";
    el.style.boxShadow = "";
  }
}

function applyFieldErrors(form, errorFields) {
  if (!Array.isArray(errorFields)) return;
  let first = null;
  for (const fieldName of errorFields) {
    const input = form.elements[fieldName];
    if (!input) continue;
    if (!first) first = input;
    input.setAttribute("data-action-field-error", "1");
    input.style.borderColor = "#ef4444";
    input.style.boxShadow = "0 0 0 2px rgba(239, 68, 68, 0.2)";
  }
  if (first && typeof first.focus === "function") first.focus();
}

async function showCapturedDataForm(button, actionDataJson, stepEuid, actionName, actionGroup) {
  const uniqueFormId = getActionFormId(stepEuid, actionName, actionGroup);
  const existing = document.getElementById(uniqueFormId);
  if (existing) {
    existing.style.display = existing.style.display === "none" ? "block" : "none";
    return;
  }

  const actionData = actionDataJson || {};
  const schema = actionData.ui_schema && typeof actionData.ui_schema === "object" ? actionData.ui_schema : {};
  const fields = Array.isArray(schema.fields)
    ? schema.fields.filter((field) => field && typeof field === "object" && String(field.name || "").trim())
    : [];
  const captureMode = String(actionData.capture_data || "").toLowerCase();

  if (captureMode === "no" || fields.length === 0) {
    await performUiAction({
      euid: stepEuid,
      action_group: actionGroup,
      action_key: actionName,
      captured_data: {},
    });
    window.location.reload();
    return;
  }

  const formContainer = document.createElement("div");
  formContainer.id = uniqueFormId;
  formContainer.setAttribute("data-testid", `action-form-${sanitizeIdSegment(actionGroup)}-${sanitizeIdSegment(actionName)}`);
  formContainer.style.display = "block";
  formContainer.style.marginTop = "0.75rem";
  formContainer.style.padding = "0.75rem";
  formContainer.style.border = "1px solid rgba(148, 163, 184, 0.35)";
  formContainer.style.borderRadius = "0.5rem";

  const errorPanel = document.createElement("div");
  errorPanel.className = "action-form-error-panel";
  errorPanel.style.display = "none";
  errorPanel.style.marginBottom = "0.75rem";
  errorPanel.style.color = "#fecaca";
  formContainer.appendChild(errorPanel);

  const form = document.createElement("form");
  form.noValidate = true;
  formContainer.appendChild(form);

  for (const field of fields) {
    const wrapper = document.createElement("div");
    const label = document.createElement("label");
    label.textContent = String(field.label || field.name);
    const options = await resolveFieldOptions(field);
    label.appendChild(createFieldInput(field, options));
    wrapper.appendChild(label);
    form.appendChild(wrapper);
  }

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "action-submit-btn";
  submit.textContent = "Submit";
  submit.setAttribute("data-testid", `action-submit-${sanitizeIdSegment(actionGroup)}-${sanitizeIdSegment(actionName)}`);
  form.appendChild(submit);

  form.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    errorPanel.style.display = "none";
    clearFieldErrors(form);
    try {
      const capturedData = await buildCapturedDataFromForm(form);
      await performUiAction({
        euid: stepEuid,
        action_group: actionGroup,
        action_key: actionName,
        captured_data: capturedData,
      });
      if (window.BloomToast && typeof window.BloomToast.success === "function") {
        window.BloomToast.success("Action Complete", "Action completed", 2000);
      }
      formContainer.remove();
      window.location.reload();
    } catch (error) {
      errorPanel.textContent = error.message || "Action failed";
      errorPanel.style.display = "block";
      applyFieldErrors(form, error.error_fields || []);
      if (window.BloomToast && typeof window.BloomToast.error === "function") {
        window.BloomToast.error("Action Failed", error.message || "Action failed");
      }
    }
  });

  const parent = button.parentElement;
  if (parent && window.getComputedStyle(parent).display.indexOf("flex") !== -1) {
    parent.insertAdjacentElement("afterend", formContainer);
  } else {
    button.insertAdjacentElement("afterend", formContainer);
  }
}

function showCapturedDataFormFromDataAttributes(button) {
  try {
    const rawActionData = button.getAttribute("data-action-json");
    if (!rawActionData) throw new Error("Missing data-action-json");
    let actionData;
    try {
      actionData = JSON.parse(rawActionData);
    } catch {
      const decoder = document.createElement("textarea");
      decoder.innerHTML = rawActionData;
      actionData = JSON.parse(decoder.value);
    }
    showCapturedDataForm(
      button,
      actionData,
      button.getAttribute("data-euid") || "",
      button.getAttribute("data-action-name") || "",
      button.getAttribute("data-action-group") || "",
    );
  } catch (error) {
    if (window.BloomToast && typeof window.BloomToast.error === "function") {
      window.BloomToast.error("Action Error", error.message || "Unable to open action form");
    }
  }
}

window.showCapturedDataForm = showCapturedDataForm;
window.showCapturedDataFormFromDataAttributes = showCapturedDataFormFromDataAttributes;
