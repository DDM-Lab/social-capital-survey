(function () {
  function buildGrid(wrap) {
    var overlay = wrap.querySelector(".grid-overlay");
    var rows = parseInt(wrap.dataset.rows, 10);
    var cols = parseInt(wrap.dataset.cols, 10);
    var rowField = document.getElementById(wrap.dataset.rowField);
    var colField = document.getElementById(wrap.dataset.colField);
    var selectedRow = wrap.dataset.selectedRow;
    var selectedCol = wrap.dataset.selectedCol;

    function select(cell) {
      overlay.querySelectorAll(".grid-cell").forEach(function (c) {
        c.classList.remove("selected");
      });
      cell.classList.add("selected");
      rowField.value = cell.dataset.row;
      colField.value = cell.dataset.col;
    }

    for (var r = 0; r < rows; r++) {
      for (var c = 0; c < cols; c++) {
        var cell = document.createElement("div");
        cell.className = "grid-cell";
        cell.dataset.row = r;
        cell.dataset.col = c;
        if (String(r) === selectedRow && String(c) === selectedCol) {
          cell.classList.add("selected");
        }
        cell.addEventListener("click", function () {
          select(this);
        });
        overlay.appendChild(cell);
      }
    }
  }

  var wraps = document.querySelectorAll(".preference-grid-wrap");
  if (!wraps.length) return;
  wraps.forEach(buildGrid);

  var yesBranch = document.getElementById("yes_branch");
  var noBranch = document.getElementById("no_branch");
  var requireNo = document.getElementById("require_no_branch_fields");
  var yesReason = document.getElementById("yes_reason");
  var noReason = document.getElementById("no_reason");
  var altRow = document.getElementById("alternative_row");
  var altCol = document.getElementById("alternative_col");

  function updateBranchVisibility() {
    var selected = document.querySelector('input[name="preferred_today"]:checked');
    var isYes = selected && selected.value === "yes";
    var isNo = selected && selected.value === "no";

    yesBranch.style.display = isYes ? "block" : "none";
    noBranch.style.display = isNo ? "block" : "none";

    if (isYes) {
      yesReason.required = true;
      noReason.required = false;
      if (requireNo && requireNo.value === "true") {
        noReason.value = "";
        altRow.value = "";
        altCol.value = "";
      }
    }

    if (isNo) {
      yesReason.required = false;
      noReason.required = requireNo && requireNo.value === "true";
      yesReason.value = "";
    }
  }

  document.querySelectorAll('input[name="preferred_today"]').forEach(function (radio) {
    radio.addEventListener("change", updateBranchVisibility);
  });
  updateBranchVisibility();
})();
