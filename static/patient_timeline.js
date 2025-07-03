// JavaScript for patient views timeline

document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('toggle-view-btn');
    if (!btn) return;

    const tableView = document.getElementById('patient-table-view');
    const timelineView = document.getElementById('timeline-view');

    let showingTimeline = false;

    const filesData = window.patientFilesData || [];
    const colorMap = window.patientColorMap || {};

    function buildTimeline() {
        const tl = document.getElementById('timeline');
        if (!tl) return;
        tl.innerHTML = '';
        const controls = document.getElementById('timeline-controls');
        if (controls) controls.innerHTML = '';

        const purposes = [...new Set(filesData.map(f => f.purpose))].filter(Boolean);
        const activePurposes = new Set(purposes);

        if (controls) {
            controls.style.marginBottom = '10px';
            purposes.forEach(p => {
                const label = document.createElement('label');
                label.style.marginRight = '10px';
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.checked = true;
                cb.addEventListener('change', () => {
                    if (cb.checked) {
                        activePurposes.add(p);
                    } else {
                        activePurposes.delete(p);
                    }
                    updateMarkers();
                });
                label.appendChild(cb);
                label.append(' ' + p);
                controls.appendChild(label);
            });
        }

        function updateMarkers() {
            tl.innerHTML = '';
            const sorted = [...filesData].sort((a,b)=>new Date(a.record_datetime || a.created) - new Date(b.record_datetime || b.created));
            sorted.forEach(file => {
                if (file.purpose && !activePurposes.has(file.purpose)) return;
                const link = document.createElement('a');
                link.href = `euid_details?euid=${encodeURIComponent(file.euid)}`;
                link.className = 'timeline-marker';
                link.style.display = 'inline-block';
                link.style.width = '16px';
                link.style.height = '16px';
                link.style.borderRadius = '50%';
                link.style.backgroundColor = colorMap[file.euid] || '#777';
                link.style.margin = '0 8px';
                link.title = file.original_file_name || file.euid;
                tl.appendChild(link);
            });
            // Re-init preview listeners for new anchors
            if (window.initializePreviewLinks) {
                window.initializePreviewLinks();
            }
        }

        updateMarkers();
    }

    btn.addEventListener('click', () => {
        showingTimeline = !showingTimeline;
        if (showingTimeline) {
            btn.textContent = 'Table View';
            tableView.style.display = 'none';
            timelineView.style.display = 'block';
            buildTimeline();
        } else {
            btn.textContent = 'Timeline View';
            timelineView.style.display = 'none';
            tableView.style.display = 'block';
        }
    });
});
