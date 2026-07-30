(function () {
  var form = document.getElementById("qform");
  var table = document.querySelector(".matrix-table");
  var message = document.getElementById("matrix_validation_message");

  if (!form || !table) return;

  var requireCompleteStartedRow = table.dataset.requireCompleteStartedRow === "true";
  var requireSingleChoicePerRow = table.dataset.requireSingleChoicePerRow === "true";

  if (!requireCompleteStartedRow && !requireSingleChoicePerRow) return;

  function clearValidationState() {
    table.querySelectorAll("tr.matrix-row-error").forEach(function (row) {
      row.classList.remove("matrix-row-error");
    });
    table.querySelectorAll("td.matrix-cell-error").forEach(function (cell) {
      cell.classList.remove("matrix-cell-error");
    });
    if (message) {
      message.hidden = true;
      message.textContent = "";
    }
  }

  function boolAttr(value) {
    return String(value).toLowerCase() === "true";
  }

  function isCellFilled(cell) {
    var kind = cell.dataset.columnKind;
    if (kind === "short_text") {
      var input = cell.querySelector("input.matrix-text-input");
      return !!(input && input.value.trim());
    }

    var inputChoice = cell.querySelector("input.matrix-choice-input");
    return !!(inputChoice && inputChoice.checked);
  }

  function validateRows() {
    clearValidationState();

    var rows = table.querySelectorAll("tbody tr[data-row-id]");
    var hasErrors = false;

    rows.forEach(function (row) {
      var cells = row.querySelectorAll("td[data-column-key]");
      var rowIsRequired = boolAttr(row.dataset.rowRequired);
      var started = false;
      var missingRequired = [];
      var checkedChoiceCount = 0;
      var checkedChoiceCells = [];

      cells.forEach(function (cell) {
        var filled = isCellFilled(cell);
        var isRequiredColumn = boolAttr(cell.dataset.columnRequired);
        var kind = cell.dataset.columnKind;

        if (filled) started = true;

        if (kind === "choice" && filled) {
          checkedChoiceCount += 1;
          checkedChoiceCells.push(cell);
        }

        if (isRequiredColumn && !filled) {
          missingRequired.push(cell);
        }
      });

      if (requireCompleteStartedRow && started && missingRequired.length) {
        hasErrors = true;
        row.classList.add("matrix-row-error");
        missingRequired.forEach(function (cell) {
          cell.classList.add("matrix-cell-error");
        });
      }

      if (requireSingleChoicePerRow && rowIsRequired) {
        if (checkedChoiceCount === 0 || checkedChoiceCount > 1) {
          hasErrors = true;
          row.classList.add("matrix-row-error");

          if (checkedChoiceCount === 0) {
            cells.forEach(function (cell) {
              if (cell.dataset.columnKind === "choice") {
                cell.classList.add("matrix-cell-error");
              }
            });
          } else {
            checkedChoiceCells.forEach(function (cell) {
              cell.classList.add("matrix-cell-error");
            });
          }
        }
      }
    });

    if (hasErrors && message) {
      if (requireSingleChoicePerRow) {
        message.textContent = "Please select exactly one option in each required row before continuing.";
      } else {
        message.textContent = "Please complete all required columns in any row you started before continuing.";
      }
      message.hidden = false;
    }

    return !hasErrors;
  }

  form.addEventListener("submit", function (event) {
    if (!validateRows()) {
      event.preventDefault();
    }
  });

  table.addEventListener("input", clearValidationState);
  table.addEventListener("change", clearValidationState);
})();
