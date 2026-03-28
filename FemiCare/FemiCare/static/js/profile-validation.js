(function () {
  const MIN_HEIGHT_CM = 50;
  const MAX_HEIGHT_CM = 250;
  const MIN_WEIGHT_KG = 2;
  const MAX_WEIGHT_KG = 300;

  function parseNumeric(value) {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function clearFieldError(field) {
    if (!field) {
      return;
    }
    field.classList.remove("is-invalid");
    field.removeAttribute("aria-invalid");
  }

  function setFieldError(field) {
    if (!field) {
      return;
    }
    field.classList.add("is-invalid");
    field.setAttribute("aria-invalid", "true");
  }

  function validateHeight(input) {
    const value = parseNumeric(input ? input.value : "");
    const isValid = value !== null && value >= MIN_HEIGHT_CM && value <= MAX_HEIGHT_CM;

    if (isValid) {
      clearFieldError(input);
    } else {
      setFieldError(input);
    }

    return isValid;
  }

  function validateWeight(input) {
    const value = parseNumeric(input ? input.value : "");
    const isValid = value !== null && value >= MIN_WEIGHT_KG && value <= MAX_WEIGHT_KG;

    if (isValid) {
      clearFieldError(input);
    } else {
      setFieldError(input);
    }

    return isValid;
  }

  function validateDOB(input) {
    if (!input || !input.value) {
      setFieldError(input);
      return false;
    }

    const selectedDate = new Date(input.value + "T00:00:00");
    if (Number.isNaN(selectedDate.getTime())) {
      setFieldError(input);
      return false;
    }

    const today = new Date();
    today.setHours(0, 0, 0, 0);

    const isValid = selectedDate <= today;
    if (isValid) {
      clearFieldError(input);
    } else {
      setFieldError(input);
    }

    return isValid;
  }

  function ensureWarningContainer(form) {
    let warning = form.querySelector("[data-profile-validation-warning]");
    if (warning) {
      return warning;
    }

    warning = document.createElement("div");
    warning.className = "profile-validation-warning alert alert-warning mb-3";
    warning.setAttribute("data-profile-validation-warning", "true");
    warning.style.display = "none";

    const firstChild = form.firstElementChild;
    if (firstChild) {
      form.insertBefore(warning, firstChild);
    } else {
      form.appendChild(warning);
    }

    return warning;
  }

  function showWarning(form, message) {
    const warning = ensureWarningContainer(form);
    warning.textContent = message;
    warning.style.display = "block";
  }

  function clearWarning(form) {
    const warning = form.querySelector("[data-profile-validation-warning]");
    if (!warning) {
      return;
    }

    warning.textContent = "";
    warning.style.display = "none";
  }

  function bindFieldValidation(field, validator, form) {
    if (!field) {
      return;
    }

    const handler = function () {
      const valid = validator(field);
      if (valid) {
        clearWarning(form);
      }
    };

    field.addEventListener("input", handler);
    field.addEventListener("blur", handler);
  }

  function setupProfileValidation(form) {
    const dobInput = form.querySelector('input[name="dob"], input[name="date_of_birth"]');
    const heightInput = form.querySelector('input[name="height_cm"]');
    const weightInput = form.querySelector('input[name="weight_kg"]');

    if (!dobInput || !heightInput || !weightInput) {
      return;
    }

    bindFieldValidation(heightInput, validateHeight, form);
    bindFieldValidation(weightInput, validateWeight, form);
    bindFieldValidation(dobInput, validateDOB, form);

    form.addEventListener("submit", function (event) {
      clearWarning(form);

      const heightValid = validateHeight(heightInput);
      const weightValid = validateWeight(weightInput);
      const dobValid = validateDOB(dobInput);

      if (!heightValid || !weightValid || !dobValid) {
        event.preventDefault();

        if (!heightValid || !weightValid) {
          showWarning(form, "Please enter a valid height and weight.");
          return;
        }

        showWarning(form, "Date of birth cannot be in the future.");
      }
    });
  }

  window.validateHeight = validateHeight;
  window.validateWeight = validateWeight;
  window.validateDOB = validateDOB;

  document.addEventListener("DOMContentLoaded", function () {
    const forms = document.querySelectorAll("form.profile-form-validation");
    forms.forEach(setupProfileValidation);
  });
})();
