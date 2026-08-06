(function () {
  function boolAttr(value) {
    return String(value).toLowerCase() === "true";
  }

  function clearCardErrors(card) {
    card.querySelectorAll(".required-invalid").forEach(function (node) {
      node.classList.remove("required-invalid");
    });

    var topErrors = card.querySelector(".validation-errors");
    if (topErrors) {
      topErrors.hidden = true;
      var errorItem = topErrors.querySelector(".msg.error");
      if (errorItem) {
        errorItem.textContent = "";
      }
    }

    var matrixMessage = card.querySelector("#matrix_validation_message");
    if (matrixMessage) {
      matrixMessage.hidden = true;
      matrixMessage.textContent = "";
    }
  }

  function setTopError(card, message) {
    var topErrors = card.querySelector(".validation-errors");
    if (!topErrors) {
      return;
    }
    var errorItem = topErrors.querySelector(".msg.error");
    if (!errorItem) {
      return;
    }
    errorItem.textContent = message;
    topErrors.hidden = false;
  }

  function markInvalid(node) {
    if (!node) {
      return;
    }

    var label = node.closest("label");
    if (label) {
      label.classList.add("required-invalid");
    }

    var tableCell = node.closest("td");
    if (tableCell) {
      tableCell.classList.add("required-invalid");
    }

    node.classList.add("required-invalid");
  }

  function validateSingle(card, required) {
    if (!required) {
      return null;
    }
    var choices = card.querySelectorAll('input[name="choice"]');
    if (!choices.length) {
      return null;
    }
    var selected = card.querySelector('input[name="choice"]:checked');
    if (selected) {
      return null;
    }
    choices.forEach(markInvalid);
    return "Please select an option.";
  }

  function validateMulti(card, required) {
    if (!required) {
      return null;
    }
    var checkboxes = card.querySelectorAll('input[name="choices"]');
    if (!checkboxes.length) {
      return null;
    }
    var checked = card.querySelectorAll('input[name="choices"]:checked');
    if (checked.length) {
      return null;
    }
    checkboxes.forEach(markInvalid);
    return "Please select at least one option.";
  }

  function validateLikert(card, required) {
    if (!required) {
      return null;
    }
    var options = card.querySelectorAll('input[name="likert"]');
    if (!options.length) {
      return null;
    }
    var selected = card.querySelector('input[name="likert"]:checked');
    if (selected) {
      return null;
    }
    options.forEach(markInvalid);
    return "Please choose a rating.";
  }

  function validateShortText(card) {
    var fields = Array.prototype.slice.call(
      card.querySelectorAll('textarea[name="text"], textarea[name^="text_"], input[name="text"], input[name^="text_"]')
    );
    if (!fields.length) {
      return null;
    }

    for (var i = 0; i < fields.length; i++) {
      var field = fields[i];
      var isRequired = field.hasAttribute("required");
      if (!isRequired) {
        continue;
      }
      if (field.value.trim()) {
        continue;
      }
      markInvalid(field);
      if (fields.length === 1) {
        return "Please enter a response.";
      }
      return "Please enter a response for field " + (i + 1) + ".";
    }

    return null;
  }

  function validateImageGrid(card, required) {
    if (!required) {
      return null;
    }
    var rowField = card.querySelector('input[name="grid_row"]');
    var colField = card.querySelector('input[name="grid_col"]');
    if (!rowField || !colField) {
      return null;
    }
    if (rowField.value !== "" && colField.value !== "") {
      return null;
    }
    var wrap = card.querySelector(".grid-wrap");
    if (wrap) {
      wrap.classList.add("required-invalid");
    }
    markInvalid(rowField);
    markInvalid(colField);
    return "Please tap a cell on the image.";
  }

  function validateMultiMatrix(card, required) {
    var table = card.querySelector(".matrix-table");
    if (!table) {
      return null;
    }

    var requireSingleChoicePerRow = table.dataset.requireSingleChoicePerRow === "true";
    var requireCompleteStartedRow = table.dataset.requireCompleteStartedRow === "true";
    var rows = Array.prototype.slice.call(table.querySelectorAll("tbody tr[data-row-id]"));

    if (requireSingleChoicePerRow) {
      for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        var rowRequired = boolAttr(row.dataset.rowRequired);
        if (!rowRequired) {
          continue;
        }
        var selected = row.querySelectorAll("input.matrix-choice-input:checked");
        if (selected.length === 1) {
          continue;
        }

        row.classList.add("required-invalid");
        row.querySelectorAll('td[data-column-kind="choice"]').forEach(function (cell) {
          cell.classList.add("required-invalid");
          var input = cell.querySelector("input.matrix-choice-input");
          if (input) {
            markInvalid(input);
          }
        });

        return "Please select exactly one option in each required row.";
      }
      return null;
    }

    if (requireCompleteStartedRow) {
      for (var r = 0; r < rows.length; r++) {
        var started = false;
        var missingRequiredCells = [];
        var cells = rows[r].querySelectorAll("td[data-column-key]");

        cells.forEach(function (cell) {
          var kind = cell.dataset.columnKind;
          var requiredColumn = boolAttr(cell.dataset.columnRequired);
          var filled = false;

          if (kind === "choice") {
            var choiceInput = cell.querySelector("input.matrix-choice-input");
            filled = !!(choiceInput && choiceInput.checked);
          } else if (kind === "short_text") {
            var textInput = cell.querySelector("input.matrix-text-input");
            filled = !!(textInput && textInput.value.trim());
          }

          if (filled) {
            started = true;
          }
          if (requiredColumn && !filled) {
            missingRequiredCells.push(cell);
          }
        });

        if (started && missingRequiredCells.length) {
          rows[r].classList.add("required-invalid");
          missingRequiredCells.forEach(function (cell) {
            cell.classList.add("required-invalid");
            var input = cell.querySelector("input");
            if (input) {
              markInvalid(input);
            }
          });
          return "Please complete all required columns in any row you started before continuing.";
        }
      }
      return null;
    }

    if (!required) {
      return null;
    }

    var requiredChoiceColumns = {};
    table.querySelectorAll('td[data-column-kind="choice"][data-column-required="true"]').forEach(function (cell) {
      requiredChoiceColumns[cell.dataset.columnKey] = true;
    });

    var missingColumn = Object.keys(requiredChoiceColumns).find(function (key) {
      return !table.querySelector('input.matrix-choice-input[data-column-key="' + key + '"]:checked');
    });

    if (missingColumn) {
      table.querySelectorAll('td[data-column-key="' + missingColumn + '"]').forEach(function (cell) {
        cell.classList.add("required-invalid");
        var input = cell.querySelector("input.matrix-choice-input");
        if (input) {
          markInvalid(input);
        }
      });
      var matrixScroll = card.querySelector(".matrix-scroll");
      if (matrixScroll) {
        matrixScroll.classList.add("required-invalid");
      }
      return "Please select at least one option in each required column.";
    }

    return null;
  }

  function validateMatrixWithGrid(card) {
    var table = card.querySelector(".matrix-table");
    var gridWrap = card.querySelector(".matrix-grid-wrap");
    if (!table || !gridWrap) {
      return null;
    }

    var rows = table.querySelectorAll("tbody tr[data-row-id]");
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var rowId = row.dataset.rowId;
      var rowRequired = boolAttr(row.dataset.rowRequired);
      if (!rowRequired) {
        continue;
      }

      var missing = false;
      var mapCell = row.querySelector('td[data-column-kind="map"][data-column-required="true"]');
      if (mapCell) {
        var toggle = card.querySelector('.map-toggle[data-row-id="' + rowId + '"]');
        var rowField = card.querySelector('#map_row_' + rowId);
        var colField = card.querySelector('#map_col_' + rowId);
        var hasMap = !!(toggle && toggle.checked && rowField && colField && rowField.value !== "" && colField.value !== "");
        if (!hasMap) {
          missing = true;
          mapCell.classList.add("required-invalid");
          if (toggle) {
            markInvalid(toggle);
          }
          gridWrap.classList.add("required-invalid");
        }
      }

      row.querySelectorAll('td[data-column-kind="short_text"][data-column-required="true"]').forEach(function (cell) {
        var textInput = cell.querySelector("input.matrix-grid-text-input");
        if (!textInput || textInput.value.trim()) {
          return;
        }
        missing = true;
        cell.classList.add("required-invalid");
        markInvalid(textInput);
      });

      if (missing) {
        row.classList.add("required-invalid");
        var rowLabel = row.querySelector("th");
        return "Please complete all required entries for row " + (rowLabel ? rowLabel.textContent.trim() : "") + ".";
      }
    }

    return null;
  }

  function validateGridPreferenceFlow(card, required) {
    var initialRow = card.querySelector('input[name="initial_row"]');
    var initialCol = card.querySelector('input[name="initial_col"]');
    if (!initialRow || !initialCol) {
      return null;
    }

    if (required && (initialRow.value === "" || initialCol.value === "")) {
      var firstWrap = card.querySelector(".preference-grid-wrap");
      if (firstWrap) {
        firstWrap.classList.add("required-invalid");
      }
      return "Please tap a cell for your initial location.";
    }

    var preferred = card.querySelector('input[name="preferred_today"]:checked');
    if (!preferred) {
      card.querySelectorAll('input[name="preferred_today"]').forEach(markInvalid);
      return "Please answer whether that spot was preferred today.";
    }

    if (preferred.value === "yes") {
      var yesReason = card.querySelector('textarea[name="yes_reason"]');
      if (yesReason && !yesReason.value.trim()) {
        markInvalid(yesReason);
        return "Please explain why it was your preferred spot.";
      }
      return null;
    }

    var requireNo = card.querySelector("#require_no_branch_fields");
    var needsNoBranch = !requireNo || requireNo.value === "true";
    if (!needsNoBranch) {
      return null;
    }

    var altRow = card.querySelector('input[name="alternative_row"]');
    var altCol = card.querySelector('input[name="alternative_col"]');
    if (!altRow || !altCol || altRow.value === "" || altCol.value === "") {
      var wraps = card.querySelectorAll(".preference-grid-wrap");
      if (wraps.length > 1) {
        wraps[1].classList.add("required-invalid");
      }
      return "Please tap a preferred alternative location.";
    }

    var noReason = card.querySelector('textarea[name="no_reason"]');
    if (noReason && !noReason.value.trim()) {
      markInvalid(noReason);
      return "Please explain why you preferred that location.";
    }

    return null;
  }

  function validateCard(card) {
    clearCardErrors(card);

    var hostForm = card.querySelector("form[data-question-type]");
    var required = boolAttr(card.dataset.questionRequired || (hostForm && hostForm.dataset.questionRequired));
    var questionType = card.dataset.questionType || (hostForm && hostForm.dataset.questionType) || "";
    var message = null;

    if (questionType === "single") {
      message = validateSingle(card, required);
    } else if (questionType === "multi") {
      message = validateMulti(card, required);
    } else if (questionType === "likert") {
      message = validateLikert(card, required);
    } else if (questionType === "short_text") {
      message = validateShortText(card);
    } else if (questionType === "image_grid") {
      message = validateImageGrid(card, required);
    } else if (questionType === "multi_matrix") {
      message = validateMultiMatrix(card, required);
    } else if (questionType === "matrix_with_grid") {
      message = validateMatrixWithGrid(card);
    } else if (questionType === "grid_preference_flow") {
      message = validateGridPreferenceFlow(card, required);
    }

    if (!message) {
      return true;
    }

    setTopError(card, message);

    var matrixMessage = card.querySelector("#matrix_validation_message");
    if (matrixMessage) {
      matrixMessage.hidden = false;
      matrixMessage.textContent = message;
    }

    return false;
  }

  function bindCardInputs(card) {
    card.querySelectorAll("input[name], textarea[name], select[name]").forEach(function (el) {
      el.addEventListener("change", function () {
        clearCardErrors(card);
      });
      el.addEventListener("input", function () {
        clearCardErrors(card);
      });
    });
  }

  var participantForm = document.getElementById("qform");
  if (participantForm) {
    var participantCard = participantForm.closest(".card");
    if (participantCard) {
      bindCardInputs(participantCard);
      participantForm.addEventListener("submit", function (event) {
        if (!validateCard(participantCard)) {
          event.preventDefault();
        }
      });
    }
  }

  var previewCards = document.querySelectorAll('section.card[data-preview-card="true"]');
  if (!previewCards.length) {
    return;
  }

  previewCards.forEach(function (card) {
    bindCardInputs(card);
    var previewButton = card.querySelector(".preview-validate-btn");
    if (previewButton) {
      previewButton.addEventListener("click", function () {
        validateCard(card);
      });
    }
  });

  document.querySelectorAll('.preview-next-link[data-validate-current-card="true"]').forEach(function (link) {
    link.addEventListener("click", function (event) {
      var card = document.querySelector('section.card[data-preview-card="true"]');
      if (!card) {
        return;
      }
      if (!validateCard(card)) {
        event.preventDefault();
      }
    });
  });
})();
