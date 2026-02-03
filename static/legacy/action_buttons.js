// sharedFunctions.js

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

                var formHTML = '<form>';
                for (var key in actionData['captured_data']) {
                    var value = actionData['captured_data'][key];

                    if (key.startsWith('_')) {
                        // If key starts with '_', append the value directly
                        formHTML += actionData['captured_data'][key];
                    } else {
                        // Check if value is an array or a string
                        if (Array.isArray(value)) {
                            // Handle array values
                            value.forEach(function(item) {
                                formHTML += key + '<input type="text" name="' + key + '[]" value="' + item + '"><br>';
                            });
                        } else {
                            // Handle string values
                            formHTML += key + '<input type="text" name="' + key + '" value="' + value + '"><br>';
                        }
                    }
                }
                formHTML += '</form>';
                formHTML += '<ul><button class="actionSubmit" onclick="submitCapturedDataForm(\'' + uniqueFormId + '\', \'' + actionName + '\', \'' + stepEuid + '\', \'' + escape(JSON.stringify(actionData)) + '\', \'' + actionGroup + '\')">Submit</button><hr></ul>';

                formContainer.innerHTML = formHTML;
                button.insertAdjacentElement('afterend', formContainer);
            }
        }
    } catch (e) {
        console.error('Error parsing action data JSON:', e);
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
    .then(response => {
        if (response.ok) {
            console.log('Response OK');
            return response.json();
        } else {
            console.log('Response not OK');
            throw new Error('Network response was not ok.');
        }
    })
    .then(data => {
        console.log('Success:', data);
        // Add a slight delay before reloading
        setTimeout(function() {
            window.location.reload();
        }, 500); // Waits for 500 milliseconds
    })
    .catch((error) => {
        console.error('Error:', error);
        setTimeout(function() {
            window.location.reload();
        }, 500); // Waits for 500 milliseconds
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

