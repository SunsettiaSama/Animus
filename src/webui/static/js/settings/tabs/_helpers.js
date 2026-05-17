/** Shared DOM helper functions for all settings tab modules. */
export const $   = id => document.getElementById(id);
export const _v  = id => $(id)?.value ?? '';
export const _c  = id => $(id)?.checked ?? false;
export const _si = (id, v) => { const el = $(id); if (el) el.value   = v ?? ''; };
export const _sc = (id, v) => { const el = $(id); if (el) el.checked = !!v;     };
