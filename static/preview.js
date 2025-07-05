document.addEventListener('DOMContentLoaded', () => {
    const previewBox = document.createElement('div');
    previewBox.id = 'file-preview-box';
    Object.assign(previewBox.style, {
        position: 'absolute',
        display: 'none',
        border: '1px solid #ccc',
        background: 'white',
        padding: '5px',
        zIndex: '1000'
    });
    document.body.appendChild(previewBox);

    const allowed = new Set(['pdf','png','jpg','jpeg','gif','bmp','tiff','svg']);
    const SIZE_LIMIT = 80 * 1024 * 1024; // 80MB

    async function fetchProperty(euid, key) {
        const resp = await fetch(`/get_node_property?euid=${encodeURIComponent(euid)}&key=${encodeURIComponent(key)}`);
        if (!resp.ok) throw new Error('failed');
        const data = await resp.json();
        return data[key];
    }

    async function resolveFileUrl(euid, uri) {
        if (!uri) return null;
        if (uri.startsWith('http')) {
            return uri;
        }
        if (uri.startsWith('s3://')) {
            const body = new URLSearchParams();
            body.append('euid', euid);
            body.append('download_type', 'file_only');
            body.append('create_metadata_file', 'no');
            body.append('ret_json', 'yes');
            const resp = await fetch('/download_file', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: body.toString()
            });
            if (!resp.ok) return null;
            const data = await resp.json();
            return data.file_download_path ? data.file_download_path.replace(/^\.\/?/, '/') : null;
        }
        return uri;
    }

    async function showPreview(event) {
        const link = event.currentTarget;
        const u = new URL(link.href);
        const euid = u.searchParams.get('euid');
        if (!euid) return;

        try {
            const fileType = await fetchProperty(euid, 'file_type');
            if (!fileType || !allowed.has(fileType.toLowerCase())) return;

            const size = parseInt(await fetchProperty(euid, 'original_file_size_bytes') || '0', 10);
            if (size > SIZE_LIMIT) {
                previewBox.textContent = `File too large for preview (${(size/1024/1024).toFixed(1)} MB)`;
                const topOffset = window.scrollY + window.innerHeight * 0.10;
                previewBox.style.left = '50%';
                previewBox.style.top = topOffset + 'px';
                previewBox.style.transform = 'translateX(-50%)';
                previewBox.style.display = 'block';
                return;
            }

            const uri = await fetchProperty(euid, 'current_s3_uri');
            const fileUrl = await resolveFileUrl(euid, uri);
            if (!fileUrl) return;

            previewBox.innerHTML = '';
            if (fileType.toLowerCase() === 'pdf') {
                previewBox.style.width = '1200px';
                previewBox.style.height = '800px';
                previewBox.innerHTML = `<embed src="${fileUrl}" type="application/pdf" style="width:100%;height:100%;">`;
                previewBox.onclick = e => e.stopPropagation();
            } else {
                previewBox.style.width = '';
                previewBox.style.height = '';
                previewBox.innerHTML = `<img src="${fileUrl}" style="max-width:600px; max-height:400px; cursor:pointer;">`;
                const img = previewBox.querySelector('img');
                img.addEventListener('click', ev => {
                    window.open(fileUrl, '_blank');
                    ev.stopPropagation();
                });

            }
            const topOffset = window.scrollY + window.innerHeight * 0.10;
            previewBox.style.left = '50%';
            previewBox.style.top = topOffset + 'px';
            previewBox.style.transform = 'translateX(-50%)';
            previewBox.style.display = 'block';
        } catch (e) {
            console.error('Preview error', e);

        }
    }

    function hidePreview() {
        previewBox.style.display = 'none';
        previewBox.innerHTML = '';
    }

    function movePreview(event) {
        // No-op: previews remain fixed once opened
    }

    let currentLink = null;
    let isDragging = false;
    let resizeInfo = null;
    const edgeSize = 8;

    function markPreviewable(link) {
        if (link.dataset.previewChecked) return;
        link.dataset.previewChecked = '1';
        const u = new URL(link.href);
        const euid = u.searchParams.get('euid');
        if (!euid) return;
        fetchProperty(euid, 'file_type').then(type => {
            if (type && allowed.has(type.toLowerCase())) {
                link.classList.add('previewable');
            }
        }).catch(() => {});
    }

    function attachPreviewLinks(root=document) {
        root.querySelectorAll('a[href*="euid_details?euid=FI"]').forEach(link => {
            markPreviewable(link);
            link.addEventListener('mouseenter', event => {
                currentLink = event.currentTarget;
                showPreview(event);
            });
        });
    }

    window.initializePreviewLinks = () => attachPreviewLinks(document);

    attachPreviewLinks(document);

    // hide the preview when clicking outside of it and the originating link
    document.addEventListener('click', event => {
        if (isDragging) return;
        if (previewBox.style.display === 'block') {
            if (!previewBox.contains(event.target) && (!currentLink || !currentLink.contains(event.target))) {
                hidePreview();
                currentLink = null;
            }
        }
    });

    // prevent clicks inside the preview from bubbling up and closing it
    previewBox.addEventListener('click', event => event.stopPropagation());

    // --- resizing logic ---

    function getEdges(e) {
        const rect = previewBox.getBoundingClientRect();
        const edges = {
            left: e.clientX - rect.left <= edgeSize,
            right: rect.right - e.clientX <= edgeSize,
            top: e.clientY - rect.top <= edgeSize,
            bottom: rect.bottom - e.clientY <= edgeSize
        };
        if (edges.left || edges.right || edges.top || edges.bottom) return edges;
        return null;
    }

    previewBox.addEventListener('mousedown', e => {
        const edges = getEdges(e);
        if (edges) {
            const rect = previewBox.getBoundingClientRect();
            resizeInfo = {
                edges,
                startX: e.clientX,
                startY: e.clientY,
                startW: rect.width,
                startH: rect.height,
                startL: rect.left,
                startT: rect.top
            };
            isDragging = true;
            e.preventDefault();
        } else {
            isDragging = true; // track simple dragging to prevent close on drag
        }
    });

    document.addEventListener('mousemove', e => {
        if (!resizeInfo) return;
        const dx = e.clientX - resizeInfo.startX;
        const dy = e.clientY - resizeInfo.startY;
        if (resizeInfo.edges.right) previewBox.style.width = resizeInfo.startW + dx + 'px';
        if (resizeInfo.edges.bottom) previewBox.style.height = resizeInfo.startH + dy + 'px';
        if (resizeInfo.edges.left) {
            previewBox.style.width = resizeInfo.startW - dx + 'px';
            previewBox.style.left = resizeInfo.startL + dx + 'px';
        }
        if (resizeInfo.edges.top) {
            previewBox.style.height = resizeInfo.startH - dy + 'px';
            previewBox.style.top = resizeInfo.startT + dy + 'px';
        }
    });

    document.addEventListener('mouseup', () => {
        resizeInfo = null;
        setTimeout(() => { isDragging = false; }, 0);
    });
});

