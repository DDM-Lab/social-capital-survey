// Build a clickable cell overlay for image-grid questions and record the
// tapped (row, col) into the hidden form fields.
(function () {
  var wrap = document.querySelector(".grid-wrap");
  if (!wrap) return;

  var overlay = wrap.querySelector(".grid-overlay");
  var rows = parseInt(wrap.dataset.rows, 10);
  var cols = parseInt(wrap.dataset.cols, 10);
  var rowField = document.getElementById("grid_row");
  var colField = document.getElementById("grid_col");
  var selRow = wrap.dataset.selectedRow;
  var selCol = wrap.dataset.selectedCol;

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
      if (String(r) === selRow && String(c) === selCol) {
        cell.classList.add("selected");
      }
      cell.addEventListener("click", function () { select(this); });
      overlay.appendChild(cell);
    }
  }
})();
