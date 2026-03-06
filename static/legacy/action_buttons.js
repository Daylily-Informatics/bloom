// sharedFunctions.js

function decodeHtmlEntities(value) {
    if (value === null || value === undefined) {
        return '';
    }
    var decoder = document.createElement('textarea');
    decoder.innerHTML = String(value);
    return decoder.value;
}

function sanitizeIdSegment(value) {
    return String(value || '').replace(/[^a-zA-Z0-9_-]/g, '_');
}

function getActionFormId(stepEuid, actionName, actionGroup) {
    return 'action-form-' + sanitizeIdSegment(stepEuid) + '-' + sanitizeIdSegment(actionGroup) + '-' + sanitizeIdSegment(actionName);
}

function getActionSchema(actionData) {
    if (!actionData || typeof actionData !== 'object') {
        return null;
    }
    if (actionData.ui_schema && Array.isArray(actionData.ui_schema.fields)) {
        return actionData.ui_schema;
    }
    return null;
}

function createFormContainer(uniqueFormId) {
    var formContainer = document.createElement('div');
    formContainer.id = uniqueFormId;
    formContainer.style.display = 'block';
    formContainer.style.flexBasis = '100%';
    formContainer.style.width = '100%';
    formContainer.style.marginTop = '0.75rem';
    formContainer.style.padding = '0.75rem';
    formContainer.style.border = '1px solid rgba(148, 163, 184, 0.35)';
    formContainer.style.borderRadius = '0.5rem';
    formContainer.style.background = 'rgba(15, 23, 42, 0.45)';
    return formContainer;
}

function createErrorPanel() {
    var errorPanel = document.createElement('div');
    errorPanel.className = 'action-form-error-panel';
    errorPanel.style.display = 'none';
    errorPanel.style.marginBottom = '0.75rem';
    errorPanel.style.padding = '0.5rem 0.75rem';
    errorPanel.style.border = '1px solid rgba(239, 68, 68, 0.85)';
    errorPanel.style.borderRadius = '0.375rem';
    errorPanel.style.background = 'rgba(127, 29, 29, 0.35)';
    errorPanel.style.color = '#fecaca';
    errorPanel.style.fontWeight = '600';
    return errorPanel;
}

function setFormError(formContainer, message) {
    if (!formContainer) {
        return;
    }
    var panel = formContainer.querySelector('.action-form-error-panel');
    if (!panel) {
        return;
    }
    panel.textContent = message || 'Action failed';
    panel.style.display = 'block';
}

function clearFormError(formContainer) {
    if (!formContainer) {
        return;
    }
    var panel = formContainer.querySelector('.action-form-error-panel');
    if (!panel) {
        return;
    }
    panel.textContent = '';
    panel.style.display = 'none';
}

function clearFieldErrors(form) {
    if (!form) {
        return;
    }
    var errored = form.querySelectorAll('[data-action-field-error="1"]');
    errored.forEach(function(el) {
        el.removeAttribute('data-action-field-error');
        el.style.borderColor = '';
        el.style.boxShadow = '';
    });
}

function findFieldInput(form, fieldName) {
    if (!form || !fieldName) {
        return null;
    }
    var elems = form.elements;
    for (var i = 0; i < elems.length; i++) {
        if (elems[i].name === fieldName) {
            return elems[i];
        }
    }
    return null;
}

function applyFieldErrors(form, errorFields) {
    if (!form || !Array.isArray(errorFields)) {
        return;
    }
    var first = null;
    errorFields.forEach(function(fieldName) {
        var input = findFieldInput(form, fieldName);
        if (!input) {
            return;
        }
        if (!first) {
            first = input;
        }
        input.setAttribute('data-action-field-error', '1');
        input.style.borderColor = '#ef4444';
        input.style.boxShadow = '0 0 0 2px rgba(239, 68, 68, 0.2)';
    });
    if (first && typeof first.focus === 'function') {
        first.focus();
    }
}

function setSubmitRunning(formContainer, running) {
    var button = formContainer ? formContainer.querySelector('.action-submit-btn') : null;
    if (!button) {
        return;
    }
    if (running) {
        button.setAttribute('disabled', 'disabled');
        button.textContent = 'Running...';
    } else {
        button.removeAttribute('disabled');
        button.textContent = 'Submit';
    }
}

function normalizeOptions(options) {
    if (!Array.isArray(options)) {
        return [];
    }
    return options
        .map(function(opt) {
            if (!opt || typeof opt !== 'object') {
                return null;
            }
            var value = String(opt.value || '').trim();
            var label = String(opt.label || value).trim();
            if (!value) {
                return null;
            }
            return { value: value, label: label };
        })
        .filter(function(opt) { return opt !== null; });
}

async function fetchWorkflowAssayOptions() {
    var response = await fetch('/api/v1/workflows/?workflow_type=assay&page_size=1000');
    var payload = await response.json().catch(function() { return {}; });
    if (!response.ok) {
        throw new Error((payload && payload.detail) || 'Failed to fetch assay options');
    }

    var items = Array.isArray(payload.items) ? payload.items : [];
    return items
        .filter(function(item) { return item && item.euid; })
        .map(function(item) {
            var label = String(item.name || item.euid) + ' [' + String(item.euid) + ']';
            return {
                value: String(item.euid),
                label: label,
            };
        });
}

async function resolveFieldOptions(field) {
    var options = normalizeOptions(field.options);
    if (options.length > 0) {
        return options;
    }
    if (field.options_source === 'workflow_assays') {
        return fetchWorkflowAssayOptions();
    }
    return [];
}

function createFieldInput(field, options) {
    var type = String(field.type || 'text').toLowerCase();
    var input = null;

    if (type === 'textarea') {
        input = document.createElement('textarea');
        input.rows = Number(field.rows || 4);
    } else if (type === 'select') {
        input = document.createElement('select');
        var selectOptions = normalizeOptions(options || []);
        if (selectOptions.length === 0) {
            var emptyOption = document.createElement('option');
            emptyOption.value = '';
            emptyOption.textContent = field.placeholder || 'No options available';
            emptyOption.selected = true;
            input.appendChild(emptyOption);
        } else {
            selectOptions.forEach(function(opt) {
                var option = document.createElement('option');
                option.value = opt.value;
                option.textContent = opt.label;
                input.appendChild(option);
            });
        }
    } else {
        input = document.createElement('input');
        if (type === 'number') {
            input.type = 'number';
            if (field.min !== undefined) {
                input.min = String(field.min);
            }
            if (field.max !== undefined) {
                input.max = String(field.max);
            }
            if (field.step !== undefined) {
                input.step = String(field.step);
            }
        } else if (type === 'file') {
            input.type = 'file';
            if (field.accept) {
                input.accept = String(field.accept);
            }
            if (field.multiple === true) {
                input.multiple = true;
            }
        } else {
            input.type = 'text';
        }
    }

    input.name = String(field.name || '').trim();
    input.required = !!field.required;
    input.className = 'action-field-input';
    input.style.display = 'block';
    input.style.width = '100%';
    input.style.maxWidth = '480px';
    input.style.marginTop = '0.25rem';
    input.style.marginBottom = '0.75rem';
    input.style.padding = '0.45rem 0.6rem';
    input.style.border = '1px solid rgba(148, 163, 184, 0.45)';
    input.style.borderRadius = '0.375rem';
    input.style.background = 'rgba(15, 23, 42, 0.85)';
    input.style.color = '#e2e8f0';

    if (type !== 'file' && field.default !== undefined && field.default !== null) {
        input.value = String(field.default);
    }

    return input;
}

async function buildSchemaFields(form, schema) {
    var fields = Array.isArray(schema.fields) ? schema.fields : [];
    for (var i = 0; i < fields.length; i++) {
        var field = fields[i];
        if (!field || typeof field !== 'object') {
            continue;
        }
        var name = String(field.name || '').trim();
        if (!name) {
            continue;
        }

        var wrapper = document.createElement('div');
        wrapper.className = 'action-field-wrapper';

        var label = document.createElement('label');
        label.textContent = String(field.label || name);
        label.style.display = 'block';
        label.style.fontSize = '0.85rem';
        label.style.fontWeight = '600';
        label.style.color = '#cbd5e1';

        var options = await resolveFieldOptions(field);
        var input = createFieldInput(field, options);
        label.appendChild(input);

        if (field.help_text) {
            var hint = document.createElement('div');
            hint.textContent = String(field.help_text);
            hint.style.fontSize = '0.75rem';
            hint.style.color = '#94a3b8';
            hint.style.marginTop = '-0.35rem';
            hint.style.marginBottom = '0.5rem';
            wrapper.appendChild(label);
            wrapper.appendChild(hint);
        } else {
            wrapper.appendChild(label);
        }

        form.appendChild(wrapper);
    }
}

function appendFormToDom(button, formContainer) {
    var parent = button.parentElement;
    if (parent && window.getComputedStyle(parent).display.indexOf('flex') !== -1) {
        parent.insertAdjacentElement('afterend', formContainer);
    } else {
        button.insertAdjacentElement('afterend', formContainer);
    }
}

async function showCapturedDataForm(button, actionDataJson, stepEuid, actionName, actionGroup) {
    try {
        var uniqueFormId = getActionFormId(stepEuid, actionName, actionGroup);
        var existingForm = document.getElementById(uniqueFormId);
        if (existingForm) {
            existingForm.style.display = existingForm.style.display === 'none' ? 'block' : 'none';
            return;
        }

        var actionData = actionDataJson || {};
        var schema = getActionSchema(actionData);
        var captureMode = String(actionData.capture_data || '').toLowerCase();
        var fields = schema && Array.isArray(schema.fields) ? schema.fields : [];

        if (captureMode === 'no' || fields.length === 0) {
            if (captureMode !== 'no') {
                var schemaMessage = 'Action template is missing ui_schema.fields: ' + actionName + '. This usually means templates are stale. Run `bloom db seed --overwrite` and hard-refresh the page.';
                if (typeof window.BloomToast !== 'undefined' && typeof window.BloomToast.error === 'function') {
                    window.BloomToast.error('Action Error', schemaMessage);
                }
                return;
            }

            try {
                var oneClickPayload = await performWorkflowStepAction({
                    euid: stepEuid,
                    action_group: actionGroup,
                    action_key: actionName,
                    captured_data: {},
                });

                if (oneClickPayload && oneClickPayload.download_url) {
                    window.open(oneClickPayload.download_url, '_blank');
                }
                if (typeof window.BloomToast !== 'undefined' && typeof window.BloomToast.success === 'function') {
                    var okMessage = (oneClickPayload && oneClickPayload.message) ? oneClickPayload.message : 'Action completed';
                    window.BloomToast.success('Action Complete', okMessage, 2000);
                }
                setTimeout(function() {
                    window.location.reload();
                }, 250);
            } catch (err) {
                console.error('One-click action failed:', err);
                var message = err && err.message ? err.message : 'Action failed';
                if (typeof window.BloomToast !== 'undefined' && typeof window.BloomToast.error === 'function') {
                    window.BloomToast.error('Action Failed', message);
                }
            }
            return;
        }

        var formContainer = createFormContainer(uniqueFormId);
        var errorPanel = createErrorPanel();
        var form = document.createElement('form');
        form.className = 'action-dynamic-form';
        form.noValidate = true;

        formContainer.appendChild(errorPanel);
        formContainer.appendChild(form);

        await buildSchemaFields(form, schema);

        var submitButton = document.createElement('button');
        submitButton.type = 'submit';
        submitButton.className = 'action-submit-btn';
        submitButton.textContent = 'Submit';
        submitButton.style.marginTop = '0.25rem';
        submitButton.style.padding = '0.45rem 0.9rem';
        submitButton.style.border = 'none';
        submitButton.style.borderRadius = '0.375rem';
        submitButton.style.background = '#6366f1';
        submitButton.style.color = '#ffffff';
        submitButton.style.fontWeight = '600';
        submitButton.style.cursor = 'pointer';
        form.appendChild(submitButton);

        form.addEventListener('submit', function(evt) {
            evt.preventDefault();
            submitCapturedDataForm(formContainer, form, stepEuid, actionName, actionGroup);
        });

        appendFormToDom(button, formContainer);
    } catch (e) {
        console.error('Error building action form:', e);
        if (typeof window.BloomToast !== 'undefined' && typeof window.BloomToast.error === 'function') {
            window.BloomToast.error('Action Error', e.message || 'Unable to open action form');
        }
    }
}

function showCapturedDataFormFromDataAttributes(button) {
    try {
        var rawActionData = button.getAttribute('data-action-json');
        if (!rawActionData) {
            throw new Error('Missing data-action-json');
        }

        var actionData;
        try {
            actionData = JSON.parse(rawActionData);
        } catch (parseError) {
            // Some browser/cache combinations may leave HTML entities encoded.
            var decoder = document.createElement('textarea');
            decoder.innerHTML = rawActionData;
            actionData = JSON.parse(decoder.value);
        }
        var stepEuid = button.getAttribute('data-euid') || '';
        var actionName = button.getAttribute('data-action-name') || '';
        var actionGroup = button.getAttribute('data-action-group') || '';

        showCapturedDataForm(button, actionData, stepEuid, actionName, actionGroup);
    } catch (e) {
        console.error('Error reading action data attributes:', e);
        if (typeof window.BloomToast !== 'undefined' && typeof window.BloomToast.error === 'function') {
            window.BloomToast.error('Action Error', e.message || 'Unable to open action form');
        }
    }
}

function readFileAsText(file) {
    if (!file) {
        return Promise.resolve('');
    }
    if (typeof file.text === 'function') {
        return file.text();
    }
    return new Promise(function(resolve, reject) {
        var reader = new FileReader();
        reader.onload = function() {
            resolve(reader.result || '');
        };
        reader.onerror = function() {
            reject(reader.error || new Error('Unable to read selected file'));
        };
        reader.readAsText(file);
    });
}

async function buildCapturedDataFromForm(form) {
    var formData = new FormData(form);
    var capturedData = {};

    var entries = [];
    formData.forEach(function(value, key) {
        entries.push([key, value]);
    });

    for (var i = 0; i < entries.length; i++) {
        var key = entries[i][0];
        var value = entries[i][1];

        if (value instanceof File) {
            if (!value.name || value.size === 0) {
                continue;
            }
            var fileText = await readFileAsText(value);
            capturedData[key + '_name'] = value.name;
            capturedData[key + '_text'] = fileText;
            capturedData[key] = fileText;
            if (key.endsWith('_file')) {
                var textKey = key.slice(0, -5);
                var prior = capturedData[textKey] || '';
                capturedData[textKey] = prior
                    ? (String(prior) + '\n' + fileText)
                    : fileText;
            }
            continue;
        }

        if (Object.prototype.hasOwnProperty.call(capturedData, key)) {
            if (Array.isArray(capturedData[key])) {
                capturedData[key].push(value);
            } else {
                capturedData[key] = [capturedData[key], value];
            }
        } else {
            capturedData[key] = value;
        }
    }

    return capturedData;
}

async function submitCapturedDataForm(formContainer, form, stepEuid, actionName, actionGroup) {
    if (!formContainer || !form) {
        return;
    }

    clearFormError(formContainer);
    clearFieldErrors(form);
    setSubmitRunning(formContainer, true);

    try {
        var capturedData = await buildCapturedDataFromForm(form);
        var responsePayload = await performWorkflowStepAction({
            euid: stepEuid,
            action_group: actionGroup,
            action_key: actionName,
            captured_data: capturedData,
        });

        if (responsePayload && responsePayload.download_url) {
            window.open(responsePayload.download_url, '_blank');
        }

        if (typeof window.BloomToast !== 'undefined' && typeof window.BloomToast.success === 'function') {
            var okMessage = (responsePayload && responsePayload.message) ? responsePayload.message : 'Action completed';
            window.BloomToast.success('Action Complete', okMessage, 2000);
        }
        formContainer.remove();
        setTimeout(function() {
            window.location.reload();
        }, 300);
    } catch (error) {
        console.error('Action submission failed:', error);
        var message = error && error.message ? error.message : 'Action failed';
        var fields = Array.isArray(error && error.error_fields) ? error.error_fields : [];
        setFormError(formContainer, message);
        applyFieldErrors(form, fields);

        if (typeof window.BloomToast !== 'undefined' && typeof window.BloomToast.error === 'function') {
            window.BloomToast.error('Action Failed', message);
        }
    } finally {
        setSubmitRunning(formContainer, false);
    }
}

async function performWorkflowStepAction(payload) {
    var response = await fetch('/workflow_step_action', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
    });

    var contentType = response.headers.get('content-type') || '';
    var parsed = null;
    if (contentType.indexOf('application/json') !== -1) {
        parsed = await response.json().catch(function() { return {}; });
    } else {
        parsed = await response.text().catch(function() { return ''; });
    }

    if (response.ok) {
        return parsed;
    }

    var message = 'Action failed';
    var fields = [];
    if (parsed && typeof parsed === 'object') {
        if (typeof parsed.detail === 'string' && parsed.detail.trim() !== '') {
            message = parsed.detail;
        } else if (parsed.detail && typeof parsed.detail === 'object' && typeof parsed.detail.message === 'string') {
            message = parsed.detail.message;
            fields = Array.isArray(parsed.detail.error_fields) ? parsed.detail.error_fields : [];
        } else if (typeof parsed.message === 'string' && parsed.message.trim() !== '') {
            message = parsed.message;
        }
        if (Array.isArray(parsed.error_fields)) {
            fields = parsed.error_fields;
        }
    } else if (typeof parsed === 'string' && parsed.trim() !== '') {
        message = parsed.trim();
    }

    var err = new Error(message);
    err.error_fields = fields;
    err.status = response.status;
    throw err;
}



document.addEventListener("DOMContentLoaded", function() {
    var acc = document.getElementsByClassName("accordion");
    
    for (var i = 0; i < acc.length; i++) {
        var accordion = acc[i];
        var state = accordion.getAttribute('data-state');
        var panel = accordion.nextElementSibling;

        // Initial setup based on 'data-state'
        if (state === 'open') {
            panel.style.display = 'block';
            accordion.classList.add("active");
        } else {
            panel.style.display = 'none';
        }

        // Add event listener to toggle display on click
        accordion.addEventListener("click", function() {
            toggleCollapsible(this);
        });
    }
});
function toggleCollapsible(element) {
    var state = element.nextElementSibling.style.display === "block" ? "closed" : "open";
    fetch("/update_accordion_state", {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ step_euid: element.id, state: state })
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.json();
    })
    .then(data => {
        console.log('State updated:', data);
    })
    .catch(error => {
        console.error('Error updating state:', error);
    });

    element.classList.toggle("active");
    var content = element.nextElementSibling;
    if (content.style.display === "block") {
        content.style.display = "none";
    } else {
        content.style.display = "block";
    }
}


  // JavaScript functions to handle adding and removing list elements
  function addListItem(stepEuid, key) {
    var list = document.getElementById('list-' + stepEuid + '-' + key);
    var input = document.createElement('input');
    input.type = 'text';
    input.name = key + '[]';
    list.appendChild(input);
}

function removeListItem(stepEuid, key) {
    var list = document.getElementById('list-' + stepEuid + '-' + key);
    if (list.childElementCount > 1) {
        list.removeChild(list.lastChild);
    }
}

function toggleJSONDisplay(rowId) {
    var oldJsonContent = document.getElementById('jsonOldContent-' + rowId);
    var newJsonContent = document.getElementById('jsonNewContent-' + rowId);
    var button = document.getElementById('jsonToggleButton-' + rowId);

    if (oldJsonContent.style.display === 'none') {
        oldJsonContent.style.display = 'table-cell';
        newJsonContent.style.display = 'table-cell';
        button.textContent = 'Hide JSON';
    } else {
        oldJsonContent.style.display = 'none';
        newJsonContent.style.display = 'none';
        button.textContent = 'Show JSON';
    }
}
