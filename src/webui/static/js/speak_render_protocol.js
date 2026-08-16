/**
 * Speak 前后端渲染协议（字段契约）。
 *
 * 原则：
 * - 后端已从 character 字符串解析并拆成字段事件；
 * - 前端只消费 kind + 约定 meta 字段渲染；
 * - 禁止在前端解析 character 原始标签字符串。
 *
 * 可见渲染字段：thought | speak | body | wait | silence | typing | finish | observe | outline
 * meta.order：同一回合内字段演出顺序（由后端按标签出现顺序编号；交替回放依此排序）
 */

export const SPEAK_RENDER_FIELDS = Object.freeze([
  'thought',
  'speak',
  'body',
  'wait',
  'silence',
  'typing',
  'finish',
  'observe',
  'outline',
]);

export const FIELD_LABELS = Object.freeze({
  thought: 'think',
  speak: 'speak',
  body: 'body',
  wait: 'wait',
  silence: 'silence',
  typing: 'typing',
  finish: 'finish',
  observe: 'narrative',
  outline: 'outline',
});

export const META_FIELD = 'field';
export const META_LABEL = 'label';
export const META_PHASE = 'phase';
export const META_WAIT_MS = 'wait_ms';
export const META_SECONDS = 'seconds';
export const META_SESSION_STATE = 'session_state';
export const META_RENDER_TIME_MS = 'render_time_ms';
export const META_ORDER = 'order';
export const META_CREATED_AT = 'created_at';

const _FIELD_SET = new Set(SPEAK_RENDER_FIELDS);

const _KIND_TO_FIELD = Object.freeze({
  thought: 'thought',
  speak: 'speak',
  segment: 'speak',
  action: 'body',
  observe: 'observe',
  outline: 'outline',
  agent_typing: 'typing',
  finish: 'finish',
});

/**
 * @param {string|null|undefined} value
 * @returns {string|null}
 */
export function normalizeRenderField(value) {
  const key = String(value ?? '').trim().toLowerCase();
  return _FIELD_SET.has(key) ? key : null;
}

/**
 * @param {string} kind
 * @param {Record<string, unknown>} [meta]
 * @returns {string|null}
 */
export function resolveRenderField(kind, meta = {}) {
  const explicit = normalizeRenderField(meta?.[META_FIELD]);
  if (explicit) return explicit;

  const kindKey = String(kind ?? '').trim().toLowerCase();
  if (kindKey === 'state') {
    const roleOp = String(meta?.role_op || meta?.wait_reason || '').trim().toLowerCase();
    if (roleOp === 'wait' || roleOp === 'silence') return roleOp;
    const label = String(meta?.[META_LABEL] || '').trim().toLowerCase();
    if (label === 'wait' || label === 'silence') return label;
    return null;
  }
  return _KIND_TO_FIELD[kindKey] ?? null;
}

/**
 * @param {string|null} field
 * @returns {string}
 */
export function fieldLabel(field) {
  if (!field) return '';
  return FIELD_LABELS[field] || field;
}

/**
 * bubble 容器 kind：speak 台词 / body 姿态（映射到既有 CSS）。
 * @param {string|null} field
 * @returns {'speak'|'action'|null}
 */
export function bubbleKindForField(field) {
  if (field === 'speak') return 'speak';
  if (field === 'body') return 'action';
  return null;
}

/**
 * @param {unknown} value
 * @returns {number|null}
 */
export function resolveRenderOrder(value) {
  if (value == null || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/**
 * @param {Array<{meta?: Record<string, unknown>}>} events
 * @returns {typeof events}
 */
export function sortEventsByOrder(events) {
  return [...(events || [])].sort((a, b) => {
    const ao = resolveRenderOrder(a?.meta?.[META_ORDER]);
    const bo = resolveRenderOrder(b?.meta?.[META_ORDER]);
    if (ao == null && bo == null) return 0;
    if (ao == null) return 1;
    if (bo == null) return -1;
    return ao - bo;
  });
}
