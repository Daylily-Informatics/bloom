# BLOOM LIMS GUI Modernization Implementation Plan

**Version**: 1.0  
**Date**: 2026-02-02  
**Author**: Forge (with Major's direction)  
**Status**: AWAITING APPROVAL

---

## Executive Summary

This plan outlines a complete UI/UX redesign of BLOOM LIMS, inspired by the `marvain` and `zebra_day` projects. The modernization introduces a cohesive dark theme design system, improved navigation, responsive layouts, and enhanced API endpoints while preserving full backward compatibility with the legacy interface.

---

## Table of Contents

1. [Phase Breakdown](#1-phase-breakdown)
2. [Design Decisions](#2-design-decisions)
3. [API Changes](#3-api-changes)
4. [File Structure](#4-file-structure)
5. [Testing Strategy](#5-testing-strategy)
6. [Migration Path](#6-migration-path)
7. [Validation Checklist](#7-validation-checklist)

---

## 1. Phase Breakdown

### Phase 1: Foundation Setup (Files & Structure)
**Estimated Files**: 3-5 new files  
**Dependencies**: None

| Task | Description |
|------|-------------|
| 1.1 | Create `static/modern/` directory structure |
| 1.2 | Create `templates/modern/` directory structure |
| 1.3 | Create `templates/legacy/` directory structure |
| 1.4 | Create `static/modern/css/bloom_modern.css` (design system) |
| 1.5 | Create `static/modern/js/bloom_modern.js` (utilities) |
| 1.6 | Create `templates/modern/base.html` (base template) |

**Deliverables**:
- Complete CSS design system with BLOOM-specific theming
- JavaScript utility library (toasts, loading overlay, clipboard, debounce)
- Base template with header, navigation, footer structure

**Commit**: `[GUI Modernization] Phase 1: Foundation setup - CSS design system and base template`

---

### Phase 2: Legacy Migration & Preservation
**Estimated Files**: ~45 moved/updated files  
**Dependencies**: Phase 1 complete

| Task | Description |
|------|-------------|
| 2.1 | Move existing templates to `templates/legacy/` |
| 2.2 | Move existing static CSS/JS to `static/legacy/` |
| 2.3 | Create `templates/legacy/base.html` wrapper |
| 2.4 | Update legacy template paths/includes |
| 2.5 | Add legacy route prefix handling in `main.py` |

**Deliverables**:
- All existing templates preserved in `templates/legacy/`
- Legacy routes accessible at `/legacy/*` prefix
- Zero breaking changes to existing functionality

**Commit**: `[GUI Modernization] Phase 2: Legacy migration - preserve existing templates`

---

### Phase 3: Modern Dashboard & Core Pages
**Estimated Files**: 8-12 new templates  
**Dependencies**: Phase 2 complete

| Task | Description |
|------|-------------|
| 3.1 | Create `templates/modern/dashboard.html` (new home) |
| 3.2 | Create `templates/modern/login.html` (shared auth) |
| 3.3 | Create `templates/modern/assays.html` |
| 3.4 | Create `templates/modern/workflows.html` |
| 3.5 | Create `templates/modern/equipment.html` |
| 3.6 | Create `templates/modern/reagents.html` |
| 3.7 | Create `templates/modern/admin.html` |
| 3.8 | Create `templates/modern/euid_details.html` |
| 3.9 | Add modern route handlers in `main.py` |

**Deliverables**:
- Modern dashboard with stat cards and quick actions
- All core pages reimplemented with modern design
- Responsive layouts for mobile/tablet/desktop

**Commit**: `[GUI Modernization] Phase 3: Core modern pages - dashboard, assays, workflows`

---

### Phase 4: Enhanced API Endpoints
**Estimated Files**: 2-4 modified/new files  
**Dependencies**: Phase 3 complete

| Task | Description |
|------|-------------|
| 4.1 | Add pagination support to existing list endpoints |
| 4.2 | Add filtering parameters to list endpoints |
| 4.3 | Enhance error responses with structured format |
| 4.4 | Add new aggregation endpoints for dashboard stats |
| 4.5 | Create Pydantic schemas for new responses |

**Deliverables**:
- Paginated API responses for all list views
- Dashboard statistics endpoint
- Consistent error response format

**Commit**: `[GUI Modernization] Phase 4: API enhancements - pagination, filtering, stats`

---

### Phase 5: Advanced Features & Polish
**Estimated Files**: 5-8 templates  
**Dependencies**: Phase 4 complete

| Task | Description |
|------|-------------|
| 5.1 | Create `templates/modern/plate_visualization.html` |
| 5.2 | Create `templates/modern/queue_details.html` |
| 5.3 | Create `templates/modern/search_results.html` |
| 5.4 | Create `templates/modern/audit_log.html` |
| 5.5 | Implement toast notifications |
| 5.6 | Implement loading overlays |
| 5.7 | Add keyboard navigation (accessibility) |

**Deliverables**:
- All remaining pages modernized
- Interactive notifications system
- Full accessibility compliance

**Commit**: `[GUI Modernization] Phase 5: Advanced features - plate viz, search, audit`

---

### Phase 6: Testing & Documentation
**Dependencies**: Phase 5 complete

| Task | Description |
|------|-------------|
| 6.1 | Run all existing tests |
| 6.2 | Add integration tests for new routes |
| 6.3 | Test legacy route compatibility |
| 6.4 | Update README.md if needed |
| 6.5 | Final review and cleanup |

**Deliverables**:
- All tests passing
- Integration tests for new functionality
- Documentation updated

**Commit**: `[GUI Modernization] Phase 6: Testing and final polish`

---

## 2. Design Decisions

### 2.1 Color Palette (BLOOM-Specific)

Based on Marvain/Zebra Day design systems, adapted for BLOOM LIMS:

```css
:root {
  /* Primary colors */
  --color-primary: #1a1a2e;      /* Header, footer, primary backgrounds */
  --color-secondary: #16213e;    /* Hover states, secondary panels */
  --color-accent: #0f3460;       /* Tertiary accents */
  --color-highlight: #6366f1;    /* Active states, links, CTAs (indigo) */

  /* Status colors - critical for LIMS status indicators */
  --color-success: #22c55e;      /* Complete, online, pass */
  --color-warning: #f59e0b;      /* In progress, pending */
  --color-error: #ef4444;        /* Exception, failed, offline */
  --color-info: #3b82f6;         /* Informational, ready */

  /* Gray scale */
  --color-gray-900: #0a0a0a;     /* Page background */
  --color-gray-800: #141414;     /* Card backgrounds */
  --color-gray-700: #1f1f1f;     /* Input backgrounds */
  --color-gray-600: #2d2d2d;     /* Borders, dividers */
  --color-gray-500: #4a4a4a;     /* Disabled states */
  --color-gray-400: #6b6b6b;     /* Muted text */
  --color-gray-300: #a3a3a3;     /* Secondary text */
  --color-gray-200: #d4d4d4;     /* Primary text */
  --color-white: #fafafa;        /* Headings, emphasis */

  /* BLOOM-specific additions */
  --color-euid: #818cf8;         /* EUID badge/highlight color */
  --color-template: #a78bfa;     /* Template type indicator */
  --color-instance: #34d399;     /* Instance type indicator */
}
```

### 2.2 Typography

| Element | Font | Weight | Size |
|---------|------|--------|------|
| Body | Inter | 400 | 16px (1rem) |
| Headings | Inter | 600-700 | 1.25rem - 2rem |
| Code/EUIDs | JetBrains Mono | 400-500 | 0.875rem |
| Labels | Inter | 500 | 0.875rem |

### 2.3 Component Library

| Component | Usage |
|-----------|-------|
| `.stat-card` | Dashboard statistics (assay counts, queue sizes) |
| `.card` | Generic content containers |
| `.badge` | Status indicators, EUID prefixes |
| `.table` | Data tables with sorting |
| `.btn` | Action buttons (primary, outline, success, error) |
| `.toast` | Notifications (success, warning, error, info) |
| `.modal` | Dialogs for confirmations, forms |
| `.form-*` | Form inputs with consistent styling |

### 2.4 Layout & Navigation

**Header Structure**:
- Fixed position below 4px accent stripe bar
- Logo/branding left
- Main navigation center (collapsible on mobile)
- User info/actions right

**Primary Navigation Items**:
1. Dashboard (home)
2. Assays
3. Workflows
4. Equipment
5. Reagents
6. Admin

### 2.5 Responsive Breakpoints

| Breakpoint | Target |
|------------|--------|
| < 768px | Mobile (single column, hamburger menu) |
| 768px - 1024px | Tablet (2-column grids) |
| > 1024px | Desktop (full layout) |

### 2.6 Accessibility Requirements

- WCAG 2.1 AA compliance target
- Color contrast ratio: minimum 4.5:1
- **Never rely on color alone** - all status indicators include icons
- Keyboard navigation for all interactive elements
- `aria-label` on icon-only buttons
- Semantic HTML (nav, main, header, footer)

---

## 3. API Changes

### 3.1 Existing Endpoints to Enhance

| Endpoint | Enhancement |
|----------|-------------|
| `GET /api/v1/objects` | Add `page`, `per_page`, `sort_by`, `order` params |
| `GET /api/v1/workflows` | Add `status` filter, pagination |
| `GET /api/v1/templates` | Add `super_type` filter, pagination |
| `GET /api/v1/equipment` | Add `btype` filter, pagination |
| `GET /api/v1/containers` | Add `container_type` filter, pagination |

### 3.2 New Endpoints

```python
# Dashboard statistics
GET /api/v1/stats/dashboard
Response: {
  "assays": {"total": int, "in_progress": int, "complete": int, "exception": int},
  "workflows": {"by_type": {...}, "by_status": {...}},
  "equipment": {"total": int, "by_type": {...}},
  "recent_activity": [...]
}

# Quick search
GET /api/v1/search?q={query}&types={comma-separated-types}
Response: {
  "results": [...],
  "total": int,
  "page": int,
  "per_page": int
}
```

### 3.3 Response Schema Enhancements

All list endpoints will return:
```python
{
  "items": [...],
  "total": int,
  "page": int,
  "per_page": int,
  "pages": int
}
```

Error responses:
```python
{
  "error": {
    "code": str,
    "message": str,
    "details": {...}  # optional
  }
}
```

---

## 4. File Structure

### 4.1 New Directory Organization

```
bloom/
├── static/
│   ├── modern/                    # NEW: Modern UI assets
│   │   ├── css/
│   │   │   └── bloom_modern.css   # Main design system
│   │   ├── js/
│   │   │   └── bloom_modern.js    # Utilities
│   │   └── favicon.svg            # Modern favicon
│   ├── legacy/                    # MOVED: Existing assets
│   │   ├── skins/
│   │   │   ├── bloom.css
│   │   │   ├── fdx_a.css
│   │   │   └── vlight.css
│   │   ├── action_buttons.js
│   │   ├── mobile.js
│   │   └── style.css
│   └── js/                        # UNCHANGED: Shared utilities
│       └── dag-explorer/
├── templates/
│   ├── modern/                    # NEW: Modern templates
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── login.html
│   │   ├── assays.html
│   │   ├── workflows.html
│   │   ├── equipment.html
│   │   ├── reagents.html
│   │   ├── admin.html
│   │   ├── euid_details.html
│   │   ├── plate_visualization.html
│   │   ├── queue_details.html
│   │   ├── search_results.html
│   │   └── audit_log.html
│   └── legacy/                    # MOVED: Existing templates
│       ├── base.html              # NEW wrapper for legacy
│       ├── bloom_header.html
│       ├── lims_main.html
│       ├── assay.html
│       ├── admin.html
│       └── ... (all existing templates)
└── bloom_lims/
    └── api/
        └── v1/
            └── stats.py           # NEW: Dashboard stats endpoint
```

### 4.2 Legacy File Relocation Map

| Original Location | New Location |
|-------------------|--------------|
| `templates/*.html` | `templates/legacy/*.html` |
| `static/skins/*.css` | `static/legacy/skins/*.css` |
| `static/action_buttons.js` | `static/legacy/action_buttons.js` |
| `static/mobile.js` | `static/legacy/mobile.js` |
| `static/style.css` | `static/legacy/style.css` |

**Note**: `static/js/dag-explorer/` remains unchanged as shared utility.

---

## 5. Testing Strategy

### 5.1 Test Organization

Tests remain in existing `tests/` directory. No new test files will be created unless explicitly requested.

### 5.2 Coverage Targets

| Area | Target |
|------|--------|
| New API endpoints | >80% |
| Route handlers | All routes return 200/expected status |
| Legacy compatibility | 100% backward compatible |

### 5.3 Test Approach

1. **Existing Tests**: All must pass before each commit
2. **Manual Testing**: Each modern page verified in browser
3. **Legacy Verification**: Confirm `/legacy/*` routes work identically
4. **Responsive Testing**: Verify at mobile, tablet, desktop breakpoints

### 5.4 Test Commands

```bash
# Activate environment
source bloom_activate.sh

# Run all tests
pytest

# Run with coverage
pytest --cov=bloom_lims --cov-report=term-missing
```

---

## 6. Migration Path

### 6.1 URL Structure During Transition

| URL Pattern | Serves |
|-------------|--------|
| `/` | Modern dashboard (new default) |
| `/login` | Shared login page |
| `/assays` | Modern assays page |
| `/legacy/` | Legacy home (index.html) |
| `/legacy/lims` | Legacy LIMS main |
| `/legacy/assays` | Legacy assays page |
| `/legacy/*` | All legacy routes |

### 6.2 Toggle Between UIs

- Modern UI header includes: `<a href="/legacy/" class="btn btn-outline btn-sm">Legacy UI</a>`
- Legacy UI header includes: `<a href="/" class="btn btn-outline btn-sm">Modern UI</a>`

### 6.3 User Preference Storage

User preference for UI mode stored in `etc/udat.json`:
```json
{
  "user@example.com": {
    "style_css": "static/legacy/skins/bloom.css",
    "ui_mode": "modern",  // NEW field: "modern" | "legacy"
    "print_lab": "..."
  }
}
```

### 6.4 Timeline for Legacy Deprecation

| Phase | Action |
|-------|--------|
| Initial Release | Both UIs available, modern is default |
| +30 days | Announce legacy deprecation timeline |
| +90 days | Legacy UI hidden (accessible via direct URL) |
| +180 days | Consider legacy removal (with user approval) |

### 6.5 Rollback Plan

If critical issues arise:
1. Set `/` route to redirect to `/legacy/`
2. User preference `ui_mode` default to `"legacy"`
3. No code deletion until legacy deprecation approved

---

## 7. Validation Checklist

### 7.1 Per-Phase Completion Criteria

#### Phase 1 Complete When:
- [ ] `static/modern/css/bloom_modern.css` exists with full design system
- [ ] `static/modern/js/bloom_modern.js` exists with utility functions
- [ ] `templates/modern/base.html` renders correctly
- [ ] All existing tests pass

#### Phase 2 Complete When:
- [ ] All templates moved to `templates/legacy/`
- [ ] All static assets moved to `static/legacy/`
- [ ] `/legacy/*` routes work identically to original
- [ ] All existing tests pass

#### Phase 3 Complete When:
- [ ] Modern dashboard displays dashboard stats
- [ ] All core pages render with modern design
- [ ] Navigation works between all modern pages
- [ ] All existing tests pass

#### Phase 4 Complete When:
- [ ] Pagination works on list endpoints
- [ ] Dashboard stats endpoint returns data
- [ ] Error responses follow new format
- [ ] All existing tests pass

#### Phase 5 Complete When:
- [ ] All remaining pages modernized
- [ ] Toast notifications functional
- [ ] Keyboard navigation works
- [ ] All existing tests pass

#### Phase 6 Complete When:
- [ ] All tests passing
- [ ] Manual browser testing complete
- [ ] Legacy UI verified functional
- [ ] Ready for PR

### 7.2 Final Acceptance Criteria

- [ ] **All existing tests pass** (`pytest` exits 0)
- [ ] **Modern UI accessible at `/`** with full functionality
- [ ] **Legacy UI accessible at `/legacy/`** with zero regressions
- [ ] **Toggle between UIs** works in both directions
- [ ] **EUIDs display correctly** (no leading zeros, e.g., `CX1` not `CX001`)
- [ ] **Responsive design** works at 768px and 1024px breakpoints
- [ ] **Color-blind accessible** - status indicators include icons
- [ ] **Authentication works** on both modern and legacy UIs
- [ ] **Code formatted with Black** (88 char line length)
- [ ] **No new dependencies added** without explicit approval

---

## Approval Request

Major, please review this implementation plan. Once approved, I will:

1. Create the feature branch `feature/gui-modernization`
2. Proceed through phases autonomously
3. Commit after each phase with specified commit messages
4. Push to remote after each successful phase
5. Create a PR when Phase 6 is complete

**Awaiting your approval to proceed.**

