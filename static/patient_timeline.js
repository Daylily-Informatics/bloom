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

        const purposeCombos = [...new Set(filesData.map(f => `${f.purpose || ''} ${f.purpose_subtype || ''}`.trim()))].filter(Boolean);
        const categoryCombos = [...new Set(filesData.map(f => `${f.category || ''} ${f.sub_category || ''} ${f.sub_category_2 || ''}`.trim()))].filter(Boolean);
        const activePurposes = new Set(purposeCombos);
        const activeCategories = new Set(categoryCombos);

        if (controls) {
            controls.style.marginBottom = '10px';
            purposeCombos.forEach(p => {
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
            controls.appendChild(document.createElement('br'));
            categoryCombos.forEach(c => {
                const label = document.createElement('label');
                label.style.marginRight = '10px';
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.checked = true;
                cb.addEventListener('change', () => {
                    if (cb.checked) {
                        activeCategories.add(c);
                    } else {
                        activeCategories.delete(c);
                    }
                    updateMarkers();
                });
                label.appendChild(cb);
                label.append(' ' + c);
                controls.appendChild(label);
            });
        }

        function updateMarkers() {
            tl.innerHTML = '';
            const sorted = [...filesData].sort((a,b)=>new Date(a.record_datetime || a.created) - new Date(b.record_datetime || b.created));
            const groups = {};
            sorted.forEach(file => {
                const pCombo = `${file.purpose || ''} ${file.purpose_subtype || ''}`.trim();
                const cCombo = `${file.category || ''} ${file.sub_category || ''} ${file.sub_category_2 || ''}`.trim();
                if (pCombo && !activePurposes.has(pCombo)) return;
                if (cCombo && !activeCategories.has(cCombo)) return;
                const d = new Date(file.record_datetime || file.created);
                const key = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-01`;
                if (!groups[key]) groups[key] = [];
                groups[key].push(file);
            });

            Object.keys(groups).sort().forEach(key => {
                const bin = document.createElement('div');
                bin.style.display = 'inline-flex';
                bin.style.flexDirection = 'column-reverse';
                bin.style.alignItems = 'center';
                bin.style.width = '60px';
                bin.style.margin = '0 5px';

                const label = document.createElement('div');
                label.textContent = key;
                label.style.fontSize = '14px';
                label.style.fontWeight = 'bold';
                label.style.marginTop = '20px';
                bin.appendChild(label);

                groups[key].forEach(file => {
                    const wrapper = document.createElement('div');
                    wrapper.style.display = 'flex';
                    wrapper.style.flexDirection = 'column';
                    wrapper.style.alignItems = 'center';

                    const fname = document.createElement('div');
                    fname.textContent = file.original_file_name || file.euid;
                    fname.style.fontSize = '9px';
                    fname.style.transform = 'rotate(45deg)';
                    fname.style.whiteSpace = 'nowrap';
                    wrapper.appendChild(fname);

                    const link = document.createElement('a');
                    link.href = `euid_details?euid=${encodeURIComponent(file.euid)}`;
                    link.className = 'timeline-marker';
                    link.style.display = 'block';
                    link.style.width = '12px';
                    link.style.height = '12px';
                    link.style.borderRadius = '50%';
                    link.style.backgroundColor = colorMap[file.euid] || '#777';
                    link.style.marginTop = '3px';
                    link.title = file.original_file_name || file.euid;
                    wrapper.appendChild(link);

                    bin.appendChild(wrapper);
                });

                tl.appendChild(bin);
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
