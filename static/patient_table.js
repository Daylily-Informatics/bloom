document.addEventListener('DOMContentLoaded', () => {
    const table = document.getElementById('patient-table');
    if (!table) return;
    const tbody = table.querySelector('tbody');
    const headers = table.querySelectorAll('th');
    let currentCol = 0;
    let colorized = false;
    const colorBtn = document.getElementById('colorize-toggle');
    const palette = ['#fbb4ae', '#b3cde3', '#ccebc5', '#decbe4', '#fed9a6', '#ffffcc', '#e5d8bd', '#f2f2f2'];

    const allRows = Array.from(tbody.querySelectorAll('tr'));
    allRows.forEach(r => r.dataset.origColor = r.style.backgroundColor);

    headers.forEach((th, idx) => {
        th.style.cursor = 'pointer';
        th.addEventListener('click', () => {
            sortTable(idx, th);
            if (colorized) colorizeByColumn(idx);
        });
    });

    function sortTable(colIdx, th) {
        currentCol = colIdx;
        const rows = Array.from(tbody.querySelectorAll('tr'));
        const asc = th.dataset.asc === 'true';
        const isNumeric = rows.every(r => !isNaN(parseFloat(r.cells[colIdx].innerText.trim())));
        rows.sort((a,b)=>{
            const av = a.cells[colIdx].innerText.trim();
            const bv = b.cells[colIdx].innerText.trim();
            if (isNumeric) {
                return parseFloat(av) - parseFloat(bv);
            }
            return av.localeCompare(bv, undefined, {numeric:true, sensitivity:'base'});
        });
        if (asc) rows.reverse();
        tbody.innerHTML = '';
        rows.forEach(r=>tbody.appendChild(r));
        headers.forEach(h=>delete h.dataset.asc);
        th.dataset.asc = (!asc).toString();
    }

    function colorizeByColumn(colIdx) {
        const rows = Array.from(tbody.querySelectorAll('tr'));
        const colors = {};
        let i = 0;
        rows.forEach(r => {
            const val = r.cells[colIdx].innerText.trim();
            if (!colors[val]) {
                colors[val] = palette[i % palette.length];
                i++;
            }
            r.style.backgroundColor = colors[val];
        });
    }

    if (colorBtn) {
        colorBtn.addEventListener('click', () => {
            colorized = !colorized;
            if (colorized) {
                colorizeByColumn(currentCol);
                colorBtn.textContent = 'Uncolorize';
            } else {
                allRows.forEach(r => r.style.backgroundColor = r.dataset.origColor || '');
                colorBtn.textContent = 'Colorize';
            }
        });
    }

    const downloadBtn = document.getElementById('download-tsv-btn');
    if (downloadBtn) {
        downloadBtn.addEventListener('click', () => {
            const rows = Array.from(table.querySelectorAll('tr'));
            const data = rows.map(r => Array.from(r.children).map(c=>c.innerText.trim().replace(/\s+/g,' ')).join('\t')).join('\n');
            const blob = new Blob([data], {type:'text/tab-separated-values'});
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            const pid = window.currentPatientId || 'patient';
            a.download = `dewey_patient_view_${pid}.tsv`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(a.href);
        });
    }
});

