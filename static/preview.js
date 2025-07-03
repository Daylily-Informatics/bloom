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
                previewBox.style.left = event.pageX + 20 + 'px';
                previewBox.style.top = event.pageY + 20 + 'px';
                previewBox.style.display = 'block';
                return;
            }

            const uri = await fetchProperty(euid, 'current_s3_uri');
            const fileUrl = await resolveFileUrl(euid, uri);
            if (!fileUrl) return;

            previewBox.innerHTML = '';
            if (fileType.toLowerCase() === 'pdf') {
                previewBox.innerHTML = `<embed src="${fileUrl}" type="application/pdf" width="600" height="400">`;
            } else {
                previewBox.innerHTML = `<img src="${fileUrl}" style="max-width:600px; max-height:400px;">`;
            }
            previewBox.style.left = event.pageX + 20 + 'px';
            previewBox.style.top = event.pageY + 20 + 'px';
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
        if (previewBox.style.display === 'block') {
            previewBox.style.left = event.pageX + 20 + 'px';
            previewBox.style.top = event.pageY + 20 + 'px';
        }
    }

    document.querySelectorAll('a[href*="euid_details?euid=FI"]').forEach(link => {
        link.addEventListener('mouseenter', showPreview);
        link.addEventListener('mouseleave', hidePreview);
        link.addEventListener('mousemove', movePreview);
    });
});
