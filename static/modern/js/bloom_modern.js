/**
 * BLOOM LIMS Modern UI JavaScript Utilities
 * Inspired by Marvain/Zebra Day design systems
 */

// ==================== Toast Notifications ====================
const BloomToast = {
  container: null,
  
  init() {
    if (!this.container) {
      this.container = document.createElement('div');
      this.container.className = 'toast-container';
      this.container.setAttribute('aria-live', 'polite');
      document.body.appendChild(this.container);
    }
  },
  
  show(type, title, message, duration = 5000) {
    this.init();
    
    const icons = {
      success: 'fa-check-circle',
      warning: 'fa-exclamation-triangle',
      error: 'fa-times-circle',
      info: 'fa-info-circle'
    };
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
      <i class="toast-icon fas ${icons[type] || icons.info}"></i>
      <div class="toast-content">
        <div class="toast-title">${title}</div>
        ${message ? `<div class="toast-message">${message}</div>` : ''}
      </div>
      <button class="toast-close" aria-label="Close notification">&times;</button>
    `;
    
    const closeBtn = toast.querySelector('.toast-close');
    closeBtn.addEventListener('click', () => this.dismiss(toast));
    
    this.container.appendChild(toast);
    
    if (duration > 0) {
      setTimeout(() => this.dismiss(toast), duration);
    }
    
    return toast;
  },
  
  dismiss(toast) {
    if (!toast || !toast.parentNode) return;
    toast.classList.add('toast-out');
    setTimeout(() => toast.remove(), 200);
  },
  
  success(title, message, duration) { return this.show('success', title, message, duration); },
  warning(title, message, duration) { return this.show('warning', title, message, duration); },
  error(title, message, duration) { return this.show('error', title, message, duration); },
  info(title, message, duration) { return this.show('info', title, message, duration); }
};

// ==================== Loading Overlay ====================
const BloomLoading = {
  overlay: null,
  
  init() {
    if (!this.overlay) {
      this.overlay = document.createElement('div');
      this.overlay.className = 'loading-overlay';
      this.overlay.innerHTML = `
        <div class="loading-content">
          <div class="loading-spinner"></div>
          <div class="loading-text">Loading...</div>
        </div>
      `;
      document.body.appendChild(this.overlay);
    }
  },
  
  show(message = 'Loading...') {
    this.init();
    this.overlay.querySelector('.loading-text').textContent = message;
    this.overlay.classList.add('active');
    document.body.style.overflow = 'hidden';
  },
  
  hide() {
    if (this.overlay) {
      this.overlay.classList.remove('active');
      document.body.style.overflow = '';
    }
  }
};

// ==================== Clipboard ====================
async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    BloomToast.success('Copied', 'Text copied to clipboard', 2000);
    return true;
  } catch (err) {
    // Fallback for older browsers
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand('copy');
      BloomToast.success('Copied', 'Text copied to clipboard', 2000);
      return true;
    } catch (e) {
      BloomToast.error('Error', 'Failed to copy to clipboard', 3000);
      return false;
    } finally {
      textarea.remove();
    }
  }
}

// ==================== Debounce ====================
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

// ==================== Mobile Menu Toggle ====================
function initMobileMenu() {
  const toggle = document.querySelector('.menu-toggle');
  const nav = document.querySelector('.header-nav');
  
  if (toggle && nav) {
    toggle.addEventListener('click', () => {
      nav.classList.toggle('active');
      toggle.setAttribute('aria-expanded', nav.classList.contains('active'));
    });
  }
}

// ==================== Initialize ====================
document.addEventListener('DOMContentLoaded', () => {
  initMobileMenu();
});

// Export for global access
window.BloomToast = BloomToast;
window.BloomLoading = BloomLoading;
window.copyToClipboard = copyToClipboard;
window.debounce = debounce;

