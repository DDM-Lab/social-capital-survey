// Persist admin preview input state in sessionStorage so demo values survive
// step navigation. This does not write to SurveySession/Answer tables.
(function () {
  var cards = document.querySelectorAll("section.card[id^='q-']");
  if (!cards.length) return;

  var storageKey = "survey_admin_preview_state:" + window.location.pathname;
  var state = {};
  try {
    state = JSON.parse(sessionStorage.getItem(storageKey) || "{}");
  } catch (e) {
    state = {};
  }

  function readFieldValue(el) {
    if (el.type === "checkbox" || el.type === "radio") {
      return !!el.checked;
    }
    return el.value;
  }

  function writeFieldValue(el, value) {
    if (el.type === "checkbox" || el.type === "radio") {
      el.checked = !!value;
      return;
    }
    el.value = value == null ? "" : String(value);
  }

  function saveState(card) {
    var key = card.id;
    var values = {};
    card.querySelectorAll("input[name], textarea[name], select[name]").forEach(function (el) {
      var name = el.name;
      if (el.type === "radio") {
        if (!values[name]) values[name] = [];
        if (el.checked) {
          values[name] = [{ type: "radio", value: el.value, checked: true }];
        }
        return;
      }
      if (el.type === "checkbox") {
        if (!values[name]) values[name] = [];
        values[name].push({ type: "checkbox", value: el.value, checked: el.checked });
        return;
      }
      values[name] = [{ type: "value", value: readFieldValue(el) }];
    });
    state[key] = values;
    sessionStorage.setItem(storageKey, JSON.stringify(state));
  }

  function restoreState(card) {
    var key = card.id;
    var values = state[key];
    if (!values) return;

    card.querySelectorAll("input[name], textarea[name], select[name]").forEach(function (el) {
      var entries = values[el.name];
      if (!entries) return;

      if (el.type === "radio") {
        var selected = entries[0] && entries[0].value;
        el.checked = el.value === selected;
      } else if (el.type === "checkbox") {
        var match = entries.find(function (entry) {
          return entry.value === el.value;
        });
        if (match) {
          el.checked = !!match.checked;
        }
      } else {
        writeFieldValue(el, entries[0] && entries[0].value);
      }
    });

    // Trigger listeners that drive conditional/derived UI.
    card.querySelectorAll("input[name], textarea[name], select[name]").forEach(function (el) {
      el.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }

  cards.forEach(function (card) {
    restoreState(card);
    card.querySelectorAll("input[name], textarea[name], select[name]").forEach(function (el) {
      el.addEventListener("change", function () {
        saveState(card);
      });
      el.addEventListener("input", function () {
        saveState(card);
      });
    });
  });
})();
