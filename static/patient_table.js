document.addEventListener('DOMContentLoaded', () => {
    const table = document.getElementById('patient-table');
    if (!table) return;
    const tbody = table.tBodies[0];
    const headers = table.querySelectorAll('th');
    headers.forEach((th, idx) => {
        th.style.cursor = 'pointer';
        th.addEventListener('click', () => sortTable(idx, th));
    });

    function sortTable(colIdx, th) {
        const rows = Array.from(tbody.querySelectorAll('tr'));
        const asc = th.dataset.asc === 'true';
        rows.sort((a,b)=>{
            const av = a.cells[colIdx].innerText.trim();
            const bv = b.cells[colIdx].innerText.trim();
            return av.localeCompare(bv, undefined, {numeric:true});
        });
        if (asc) rows.reverse();
        tbody.innerHTML = '';
        rows.forEach(r=>tbody.appendChild(r));
        headers.forEach(h=>delete h.dataset.asc);
        th.dataset.asc = (!asc).toString();
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

