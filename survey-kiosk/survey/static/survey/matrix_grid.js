(function () {
  var wrap = document.querySelector(".matrix-grid-wrap");
  if (!wrap) return;

  var overlay = wrap.querySelector(".grid-overlay");
  var rows = parseInt(wrap.dataset.rows, 10);
  var cols = parseInt(wrap.dataset.cols, 10);
  var activeRowId = null;

  function setRowCoordinate(rowId, row, col) {
    var rowField = document.getElementById("map_row_" + rowId);
    var colField = document.getElementById("map_col_" + rowId);
    var coord = document.getElementById("map_coord_" + rowId);
    if (!rowField || !colField || !coord) return;
    rowField.value = row;
    colField.value = col;
    coord.textContent = "(" + row + ", " + col + ")";
  }

  function clearRowCoordinate(rowId) {
    var rowField = document.getElementById("map_row_" + rowId);
    var colField = document.getElementById("map_col_" + rowId);
    var coord = document.getElementById("map_coord_" + rowId);
    if (!rowField || !colField || !coord) return;
    rowField.value = "";
    colField.value = "";
    coord.textContent = "";
  }

  function selectCell(row, col) {
    overlay.querySelectorAll(".grid-cell").forEach(function (cell) {
      cell.classList.remove("selected");
    });
    var selector = '.grid-cell[data-row="' + row + '"][data-col="' + col + '"]';
    var target = overlay.querySelector(selector);
    if (target) {
      target.classList.add("selected");
    }
  }

  function setActiveRow(rowId) {
    activeRowId = rowId;
    var rowField = document.getElementById("map_row_" + rowId);
    var colField = document.getElementById("map_col_" + rowId);
    if (!rowField || !colField || rowField.value === "" || colField.value === "") return;
    selectCell(rowField.value, colField.value);
  }

  for (var r = 0; r < rows; r++) {
    for (var c = 0; c < cols; c++) {
      var cell = document.createElement("div");
      cell.className = "grid-cell";
      cell.dataset.row = r;
      cell.dataset.col = c;
      cell.addEventListener("click", function () {
        if (!activeRowId) return;
        setRowCoordinate(activeRowId, this.dataset.row, this.dataset.col);
        var toggle = document.querySelector('.map-toggle[data-row-id="' + activeRowId + '"]');
        if (toggle) toggle.checked = true;
        selectCell(this.dataset.row, this.dataset.col);
      });
      overlay.appendChild(cell);
    }
  }

  document.querySelectorAll(".map-toggle").forEach(function (toggle) {
    toggle.addEventListener("change", function () {
      var rowId = this.dataset.rowId;
      if (this.checked) {
        setActiveRow(rowId);
      } else {
        clearRowCoordinate(rowId);
        if (activeRowId === rowId) {
          activeRowId = null;
          overlay.querySelectorAll(".grid-cell").forEach(function (cell) {
            cell.classList.remove("selected");
          });
        }
      }
    });

    if (toggle.checked && !activeRowId) {
      setActiveRow(toggle.dataset.rowId);
    }
  });

  document.querySelectorAll(".map-clear").forEach(function (button) {
    button.addEventListener("click", function () {
      var rowId = this.dataset.rowId;
      var toggle = document.querySelector('.map-toggle[data-row-id="' + rowId + '"]');
      if (toggle) toggle.checked = false;
      clearRowCoordinate(rowId);
      if (activeRowId === rowId) {
        activeRowId = null;
      }
      overlay.querySelectorAll(".grid-cell").forEach(function (cell) {
        cell.classList.remove("selected");
      });
    });
  });
})();
