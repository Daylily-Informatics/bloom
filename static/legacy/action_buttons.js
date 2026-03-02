// sharedFunctions.js

function decodeHtmlEntities(value) {
    if (value === null || value === undefined) {
        return '';
    }
    var decoder = document.createElement('textarea');
    decoder.innerHTML = String(value);
    return decoder.value;
}

function showCapturedDataForm(button, actionDataJson, stepEuid, actionName, actionGroup) {
    try {
        var uniqueFormId = stepEuid + '-' + actionName + actionGroup + '-form';
        var existingForm = document.getElementById(uniqueFormId);

        // Check if the form already exists
        if (existingForm) {
            // If it exists, toggle its display
            existingForm.style.display = existingForm.style.display === 'none' ? 'block' : 'none';
        } else {
            // If it does not exist, create the form
            var actionData = actionDataJson;
            if (actionData['capture_data'] === 'no') {
                // Directly submit the form without capturing user input
                performWorkflowStepAction(stepEuid, actionDataJson, actionName, actionGroup);
            } else {
                // Create the form for user input
                var formContainer = document.createElement('div');
                formContainer.id = uniqueFormId;
                formContainer.style.display = 'block'; // Ensure the form is visible when first created
                formContainer.style.flexBasis = '100%';
                formContainer.style.width = '100%';
                formContainer.style.marginTop = '0.75rem';
                formContainer.style.padding = '0.75rem';
                formContainer.style.border = '1px solid rgba(148, 163, 184, 0.35)';
                formContainer.style.borderRadius = '0.5rem';
                formContainer.style.background = 'rgba(15, 23, 42, 0.45)';

                var formHTML = '<form>';
                for (var key in actionData['captured_data']) {
                    var value = actionData['captured_data'][key];

                    if (key.startsWith('_')) {
                        // Key-prefixed values are authored as HTML snippets and may be entity-encoded.
                        formHTML += decodeHtmlEntities(value);
                    } else {
                        // Check if value is an array or a string
                        if (Array.isArray(value)) {
                            // Handle array values
                            value.forEach(function(item) {
                                formHTML += key + '<input type="text" name="' + key + '[]" value="' + item + '"><br>';
                            });
                        } else {
                            // Handle string values
                            formHTML += key + '<input type="text" name="' + key + '" value="' + decodeHtmlEntities(value) + '"><br>';
                        }
                    }
                }
                formHTML += '</form>';
                formHTML += '<ul><button class="actionSubmit" onclick="submitCapturedDataForm(\'' + uniqueFormId + '\', \'' + actionName + '\', \'' + stepEuid + '\', \'' + escape(JSON.stringify(actionData)) + '\', \'' + actionGroup + '\')">Submit</button><hr></ul>';

                formContainer.innerHTML = formHTML;

                var parent = button.parentElement;
                if (parent && window.getComputedStyle(parent).display.indexOf('flex') !== -1) {
                    parent.insertAdjacentElement('afterend', formContainer);
                } else {
                    button.insertAdjacentElement('afterend', formContainer);
                }
            }
        }
    } catch (e) {
        console.error('Error parsing action data JSON:', e);
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

function submitCapturedDataForm(formId, actionName, stepEuid, actionDataJson, actionGroup) {
    var formContainer = document.getElementById(formId);
    var form = formContainer.querySelector('form');
    var formData = new FormData(form);
    var updatedActionData = {};
    var actionData = JSON.parse(unescape(actionDataJson));

    formData.forEach(function(value, key){
        actionData['captured_data'][key] = value;
    });

    // Now call the original function with updated data
    performWorkflowStepAction(stepEuid, actionData, actionName, actionGroup);

    // Remove the form from the DOM
    formContainer.remove();
}

function performWorkflowStepAction(stepEuid, ds, action, actionGroup) {
    console.log('Performing workflow step action:', stepEuid, ds, action, actionGroup); // Debugging log

    fetch('/workflow_step_action', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ action_group: actionGroup, euid: stepEuid, action: action, ds: ds })
    })
    .then(async response => {
        var contentType = response.headers.get('content-type') || '';
        var payload = null;
        if (contentType.indexOf('application/json') !== -1) {
            payload = await response.json();
        } else {
            payload = await response.text();
        }

        if (response.ok) {
            console.log('Response OK', payload);
            return payload;
        }

        var message = 'Action failed';
        if (payload && typeof payload === 'object') {
            message = payload.detail || payload.message || message;
        } else if (typeof payload === 'string' && payload.trim() !== '') {
            message = payload;
        }
        throw new Error(message);
    })
    .then(data => {
        console.log('Success:', data);
        if (typeof window.BloomToast !== 'undefined' && typeof window.BloomToast.success === 'function') {
            var msg = (data && data.message) ? data.message : 'Action completed';
            window.BloomToast.success('Action Complete', msg, 2000);
        }
        // Add a slight delay before reloading
        setTimeout(function() {
            window.location.reload();
        }, 500); // Waits for 500 milliseconds
    })
    .catch((error) => {
        console.error('Error:', error);
        if (typeof window.BloomToast !== 'undefined' && typeof window.BloomToast.error === 'function') {
            window.BloomToast.error('Action Error', error.message || 'Request failed');
        }
    });
}

// Additional shared functions can be added here as needed.



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
