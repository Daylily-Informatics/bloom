/**
 * BLOOM LIMS Mobile/Tablet JavaScript Enhancements
 * Provides touch-friendly interactions and responsive behavior
 */

(function() {
    'use strict';

    // Configuration
    const MOBILE_BREAKPOINT = 768;
    const TOUCH_HOLD_DELAY = 500;
    const SWIPE_THRESHOLD = 50;

    // State
    let touchStartX = 0;
    let touchStartY = 0;
    let touchStartTime = 0;

    /**
     * Check if device is mobile/tablet
     */
    function isMobile() {
        return window.innerWidth <= MOBILE_BREAKPOINT || 
               ('ontouchstart' in window) ||
               (navigator.maxTouchPoints > 0);
    }

    /**
     * Initialize mobile menu toggle
     */
    function initMobileMenu() {
        const header = document.querySelector('.header-container');
        if (!header) return;

        // Create mobile menu toggle button
        const menuToggle = document.createElement('button');
        menuToggle.className = 'mobile-menu-toggle';
        menuToggle.setAttribute('aria-label', 'Toggle navigation menu');
        menuToggle.innerHTML = '<span></span><span></span><span></span>';

        // Create collapsible nav wrapper
        const navItems = header.querySelectorAll('small, span:not(:first-child)');
        const navWrapper = document.createElement('nav');
        navWrapper.className = 'mobile-nav';
        navWrapper.style.display = 'none';

        navItems.forEach(item => {
            if (item.tagName === 'SMALL') {
                navWrapper.appendChild(item.cloneNode(true));
            }
        });

        // Toggle menu on click
        menuToggle.addEventListener('click', function() {
            const isOpen = navWrapper.style.display !== 'none';
            navWrapper.style.display = isOpen ? 'none' : 'block';
            menuToggle.classList.toggle('active', !isOpen);
        });

        // Only add on mobile
        if (isMobile()) {
            header.appendChild(menuToggle);
            header.appendChild(navWrapper);
        }
    }

    /**
     * Add swipe gestures for navigation
     */
    function initSwipeGestures() {
        document.addEventListener('touchstart', function(e) {
            touchStartX = e.touches[0].clientX;
            touchStartY = e.touches[0].clientY;
            touchStartTime = Date.now();
        }, { passive: true });

        document.addEventListener('touchend', function(e) {
            const touchEndX = e.changedTouches[0].clientX;
            const touchEndY = e.changedTouches[0].clientY;
            const deltaX = touchEndX - touchStartX;
            const deltaY = touchEndY - touchStartY;
            const deltaTime = Date.now() - touchStartTime;

            // Only process quick swipes
            if (deltaTime > 300) return;

            // Horizontal swipe detection
            if (Math.abs(deltaX) > SWIPE_THRESHOLD && Math.abs(deltaX) > Math.abs(deltaY)) {
                if (deltaX > 0) {
                    // Swipe right - could trigger back navigation
                    handleSwipeRight();
                } else {
                    // Swipe left - could open menu
                    handleSwipeLeft();
                }
            }
        }, { passive: true });
    }

    function handleSwipeRight() {
        // Optional: implement back navigation
        // window.history.back();
    }

    function handleSwipeLeft() {
        // Optional: open side menu
        const menuToggle = document.querySelector('.mobile-menu-toggle');
        if (menuToggle) {
            menuToggle.click();
        }
    }

    /**
     * Make tables responsive with data-label attributes
     */
    function initResponsiveTables() {
        const tables = document.querySelectorAll('table');
        tables.forEach(table => {
            const headers = table.querySelectorAll('th');
            const headerTexts = Array.from(headers).map(th => th.textContent.trim());

            const rows = table.querySelectorAll('tbody tr');
            rows.forEach(row => {
                const cells = row.querySelectorAll('td');
                cells.forEach((cell, index) => {
                    if (headerTexts[index]) {
                        cell.setAttribute('data-label', headerTexts[index]);
                    }
                });
            });

            // Add responsive class
            table.classList.add('responsive-cards');
        });
    }

    /**
     * Improve touch feedback on buttons
     */
    function initTouchFeedback() {
        const buttons = document.querySelectorAll('button, .btn, .action_button, .idx_button');
        buttons.forEach(button => {
            button.addEventListener('touchstart', function() {
                this.style.transform = 'scale(0.95)';
            }, { passive: true });

            button.addEventListener('touchend', function() {
                this.style.transform = '';
            }, { passive: true });
        });
    }

    /**
     * Handle orientation changes
     */
    function initOrientationHandler() {
        window.addEventListener('orientationchange', function() {
            // Force layout recalculation
            document.body.style.display = 'none';
            document.body.offsetHeight; // Trigger reflow
            document.body.style.display = '';
        });
    }

    /**
     * Initialize pull-to-refresh (optional)
     */
    function initPullToRefresh() {
        // Implementation depends on requirements
        // Could use a library like PullToRefresh.js
    }

    /**
     * Initialize all mobile enhancements
     */
    function init() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', setup);
        } else {
            setup();
        }
    }

    function setup() {
        if (isMobile()) {
            document.body.classList.add('is-mobile');
            initMobileMenu();
            initSwipeGestures();
            initResponsiveTables();
            initTouchFeedback();
            initOrientationHandler();
        }

        // Re-check on resize
        window.addEventListener('resize', debounce(function() {
            document.body.classList.toggle('is-mobile', isMobile());
        }, 250));
    }

    /**
     * Debounce utility
     */
    function debounce(func, wait) {
        let timeout;
        return function(...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    // Export for external use
    window.BloomMobile = {
        isMobile: isMobile,
        init: init
    };

    // Auto-initialize
    init();
})();

