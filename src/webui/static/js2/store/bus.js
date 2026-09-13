/**
 * store/bus.js — 全站唯一事件总线。
 *
 * 取代旧代码中三轨并存的事件机制（eventBus + window CustomEvent + setCallbacks）。
 * 约定：
 * - 事件名使用 `domain:verb` 形式（如 `toast:show`、`conversation:loaded`）；
 * - 跨层通知一律走 bus；store 自身的字段变更走各自 subscribe；
 * - 监听器异常被隔离（一个抛错不阻断其他监听器），并以 console.warn 记录。
 */

const _listeners = new Map(); // event → Set<fn>

export const bus = {
  /**
   * 订阅事件。返回取消订阅函数。
   * @param {string} event
   * @param {(payload:any)=>void} fn
   */
  on(event, fn) {
    if (typeof fn !== 'function') return () => {};
    let set = _listeners.get(event);
    if (!set) {
      set = new Set();
      _listeners.set(event, set);
    }
    set.add(fn);
    return () => set.delete(fn);
  },

  /** 订阅一次。 */
  once(event, fn) {
    const off = this.on(event, payload => {
      off();
      fn(payload);
    });
    return off;
  },

  off(event, fn) {
    _listeners.get(event)?.delete(fn);
  },

  emit(event, payload) {
    const set = _listeners.get(event);
    if (!set || !set.size) return;
    for (const fn of [...set]) {
      try {
        fn(payload);
      } catch (err) {
        console.warn(`[bus] listener error on "${event}"`, err);
      }
    }
  },
};

// ── 全局事件名登记表 ─────────────────────────────────────────────────────────
// 集中定义避免字符串拼写漂移；新事件先登记再使用。

export const EVENTS = Object.freeze({
  // toast / 通知
  toastShow:        'toast:show',

  // 屏幕导航
  navigate:         'navigate',
  screenEnter:      'screen:enter',
  navigateRequest:  'navigate:request',     // {screen} 下层请求跳屏，router 消费

  // 账号
  accountSelected:  'account:selected',

  // 计划子面板（workspace 内嵌）
  planInitSubpanel: 'plan:init-subpanel',

  // 会话生命周期
  sessionLifecycle: 'session:lifecycle',   // {from, to}
  sessionFields:    'session:fields',      // {changed: {key: value}}
  speakReady:       'session:speak_ready',

  // 对话
  messagesChanged:  'chat:messages',       // {messages}
  turnStarted:      'chat:turn_start',
  turnFinished:     'chat:turn_finish',
  routeDecision:    'chat:route_decision',

  // Worker
  workChanged:      'work:changed',        // {item, event}
  workBusy:         'work:busy',           // {busy, activeIds}

  // 主动消息
  proactiveUnread:  'proactive:unread',    // {unread, urge}
  proactiveNotify:  'proactive:notify',    // SSE proactive_available / create_ui_request

  // 历史列表
  historyChanged:   'history:changed',     // {conversations}

  // 人格 / 模型状态
  personaName:      'persona:name',
  llmModel:         'llm:model',
});
