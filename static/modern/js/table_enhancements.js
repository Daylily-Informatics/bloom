/**
 * BLOOM table enhancements:
 * - Clickable column sorting (for tables without custom sort handlers)
 * - Row filtering
 * - CSV download (respects current filter visibility)
 */
(function () {
  const enhancedTables = new WeakSet();

  function csvEscape(value) {
    const text = String(value ?? "").replace(/\r?\n|\r/g, " ").trim();
    const escaped = text.replace(/"/g, '""');
    return `"${escaped}"`;
  }

  function normalizeCellText(cell) {
    if (!cell) {
      return "";
    }
    return String(cell.textContent || "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function parseSortableValue(raw) {
    const value = String(raw || "").trim();
    if (!value) {
      return { type: "empty", value: "" };
    }

    const normalized = value.replace(/,/g, "");
    const numeric = Number(normalized);
    if (!Number.isNaN(numeric) && normalized.match(/^[-+]?\d*\.?\d+$/)) {
      return { type: "number", value: numeric };
    }

    const parsedDate = Date.parse(value);
    if (!Number.isNaN(parsedDate)) {
      return { type: "date", value: parsedDate };
    }

    return { type: "string", value: value.toLowerCase() };
  }

  function compareRowsByColumn(rowA, rowB, columnIndex, direction) {
    const valueA = parseSortableValue(normalizeCellText(rowA.cells[columnIndex]));
    const valueB = parseSortableValue(normalizeCellText(rowB.cells[columnIndex]));

    if (valueA.type === "empty" && valueB.type !== "empty") {
      return 1;
    }
    if (valueB.type === "empty" && valueA.type !== "empty") {
      return -1;
    }

    if ((valueA.type === "number" || valueA.type === "date") && valueA.type === valueB.type) {
      return direction * (valueA.value - valueB.value);
    }

    const textA = String(valueA.value);
    const textB = String(valueB.value);
    return direction * textA.localeCompare(textB, undefined, { numeric: true, sensitivity: "base" });
  }

  function applyFilter(table, query, countEl) {
    const normalizedQuery = String(query || "").trim().toLowerCase();
    let visibleRows = 0;

    Array.from(table.tBodies[0].rows).forEach((row) => {
      const haystack = String(row.textContent || "").toLowerCase();
      const matches = !normalizedQuery || haystack.includes(normalizedQuery);
      row.style.display = matches ? "" : "none";
      if (matches) {
        visibleRows += 1;
      }
    });

    const total = table.tBodies[0].rows.length;
    if (countEl) {
      countEl.textContent = `${visibleRows}/${total} rows`;
    }
  }

  function downloadVisibleRowsCsv(table) {
    const headerRow = table.tHead ? table.tHead.rows[0] : null;
    if (!headerRow) {
      return;
    }

    const rows = [];
    const headers = Array.from(headerRow.cells).map((th) => normalizeCellText(th));
    rows.push(headers.map(csvEscape).join(","));

    Array.from(table.tBodies[0].rows).forEach((row) => {
      if (row.style.display === "none") {
        return;
      }
      const cells = Array.from(row.cells).map((td) => normalizeCellText(td));
      rows.push(cells.map(csvEscape).join(","));
    });

    const csv = rows.join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const tableId = table.id ? table.id.replace(/[^a-zA-Z0-9_-]/g, "_") : "table";
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    link.href = url;
    link.download = `${tableId}-${stamp}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function tableHasCustomSorting(table) {
    return Boolean(
      table.dataset.sortMode === "external" ||
        table.querySelector("th[onclick], th.sortable, th.sortable-col, th[data-sort]")
    );
  }

  function attachSorting(table) {
    if (!table.tHead || !table.tHead.rows.length) {
      return;
    }
    if (table.dataset.tableSort === "off" || tableHasCustomSorting(table)) {
      return;
    }

    const headerCells = Array.from(table.tHead.rows[0].cells);
    headerCells.forEach((th, index) => {
      if (th.dataset.sortOff === "1" || th.querySelector("input, button, select, textarea")) {
        return;
      }
      th.classList.add("table-sortable-col");
      th.setAttribute("role", "button");
      if (!th.hasAttribute("tabindex")) {
        th.setAttribute("tabindex", "0");
      }

      const sortHandler = () => {
        const prevIndex = Number(table.dataset.sortColumn ?? "-1");
        const prevDir = table.dataset.sortDirection === "asc" ? "asc" : "desc";
        const nextDir = prevIndex === index && prevDir === "asc" ? "desc" : "asc";
        const direction = nextDir === "asc" ? 1 : -1;

        const rows = Array.from(table.tBodies[0].rows);
        rows.sort((a, b) => compareRowsByColumn(a, b, index, direction));
        rows.forEach((row) => table.tBodies[0].appendChild(row));

        table.dataset.sortColumn = String(index);
        table.dataset.sortDirection = nextDir;
        headerCells.forEach((cell) => cell.classList.remove("sort-asc", "sort-desc"));
        th.classList.add(nextDir === "asc" ? "sort-asc" : "sort-desc");
      };

      th.addEventListener("click", sortHandler);
      th.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          sortHandler();
        }
      });
    });
  }

  function createControls(table) {
    if (!table.tBodies || !table.tBodies.length || table.dataset.tableTools === "off") {
      return null;
    }
    if (table.closest(".table-enhancement-wrap")) {
      return null;
    }

    const wrap = document.createElement("div");
    wrap.className = "table-enhancement-wrap";

    const controls = document.createElement("div");
    controls.className = "table-tools";

    const filterInput = document.createElement("input");
    filterInput.type = "search";
    filterInput.className = "form-input table-filter-input";
    filterInput.placeholder = "Filter rows...";
    filterInput.setAttribute("aria-label", "Filter table rows");

    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.className = "btn btn-outline btn-sm";
    clearBtn.textContent = "Clear";

    const downloadBtn = document.createElement("button");
    downloadBtn.type = "button";
    downloadBtn.className = "btn btn-outline btn-sm";
    downloadBtn.innerHTML = '<i class="fas fa-download"></i> Download CSV';

    const count = document.createElement("span");
    count.className = "table-filter-count text-muted";

    controls.appendChild(filterInput);
    controls.appendChild(clearBtn);
    controls.appendChild(downloadBtn);
    controls.appendChild(count);

    const parent = table.parentNode;
    parent.insertBefore(wrap, table);
    wrap.appendChild(controls);
    wrap.appendChild(table);

    filterInput.addEventListener("input", () => {
      applyFilter(table, filterInput.value, count);
    });
    clearBtn.addEventListener("click", () => {
      filterInput.value = "";
      applyFilter(table, "", count);
      filterInput.focus();
    });
    downloadBtn.addEventListener("click", () => downloadVisibleRowsCsv(table));

    applyFilter(table, "", count);
    return wrap;
  }

  function enhanceTable(table) {
    if (!(table instanceof HTMLTableElement) || enhancedTables.has(table)) {
      return;
    }
    if (!table.tHead || !table.tBodies.length) {
      return;
    }

    createControls(table);
    attachSorting(table);
    enhancedTables.add(table);
  }

  function enhanceAll(root) {
    const scope = root || document;
    scope.querySelectorAll("table").forEach((table) => enhanceTable(table));
  }

  function watchForNewTables() {
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        mutation.addedNodes.forEach((node) => {
          if (!(node instanceof Element)) {
            return;
          }
          if (node.tagName === "TABLE") {
            enhanceTable(node);
            return;
          }
          if (node.querySelectorAll) {
            enhanceAll(node);
          }
        });
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  document.addEventListener("DOMContentLoaded", () => {
    enhanceAll(document);
    watchForNewTables();
  });
})();
