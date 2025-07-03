document.addEventListener("DOMContentLoaded", function() {
    const previewBox = document.createElement('div');
    previewBox.id = 'file-preview-box';
    previewBox.style.position = 'absolute';
    previewBox.style.display = 'none';
    previewBox.style.border = '1px solid #ccc';
    previewBox.style.background = 'white';
    previewBox.style.padding = '5px';
    previewBox.style.zIndex = '1000';
    document.body.appendChild(previewBox);

    function showPreview(event) {
        const url = event.currentTarget.href;
        const ext = url.split('.').pop().toLowerCase().split(/[#?]/)[0];
        if (["pdf", "png", "jpg", "jpeg", "gif"].includes(ext)) {
            previewBox.innerHTML = '';
            if (ext === 'pdf') {
                previewBox.innerHTML = `<embed src="${url}" type="application/pdf" width="600" height="400">`;
            } else {
                previewBox.innerHTML = `<img src="${url}" style="max-width:600px; max-height:400px;">`;
            }
            previewBox.style.left = event.pageX + 20 + 'px';
            previewBox.style.top = event.pageY + 20 + 'px';
            previewBox.style.display = 'block';
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

    document.querySelectorAll('.preview-link').forEach(function(link) {
        link.addEventListener('mouseenter', showPreview);
        link.addEventListener('mouseleave', hidePreview);
        link.addEventListener('mousemove', movePreview);
    });
});

