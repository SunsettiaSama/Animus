/**
 * design.js — Single source of truth for UI conventions.
 *
 * All components reference these constants; never hard-code colors,
 * z-index values, or interaction mappings in component files.
 */

/** Z-index ladder — always use these, never raw numbers. */
export const Z = {
  drawer:    50,
  inspector: 100,
  modal:     200,
  toast:     300,
};

/** Canonical status → visual properties mapping. */
export const STATUS = {
  idle:    { label: 'IDLE',    cls: 'idle',    pulse: false },
  running: { label: 'RUNNING', cls: 'running', pulse: true  },
  pass:    { label: 'PASS',    cls: 'pass',    pulse: false },
  done:    { label: 'DONE',    cls: 'pass',    pulse: false },
  fail:    { label: 'FAIL',    cls: 'fail',    pulse: false },
  failed:  { label: 'FAIL',    cls: 'fail',    pulse: false },
  error:   { label: 'ERROR',   cls: 'fail',    pulse: false },
  pending: { label: 'PENDING', cls: 'idle',    pulse: false },
  skipped: { label: 'SKIP',    cls: 'idle',    pulse: false },
};

/**
 * Interaction contract (informational — enforced by Card and Inspector).
 *   click   → open DetailDrawer
 *   dblclick → open Inspector
 *   Escape  → close active panel
 */
export const INTERACTION = {
  primary:   'click',
  secondary: 'dblclick',
  dismiss:   'Escape',
};
