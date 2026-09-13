/**
 * ui/chat/index.js — 聊天视图 barrel。
 *
 * 说明：旧 render.js 中 ReAct 步骤渲染（appendReactMsg / appendStepBubble /
 * appendStepStrip / Full prompt）只服务于 legacy /ws/react/run 会话路径，
 * 新架构主对话不经过该路径，故不迁移（视为死代码，随旧 js/ 一并删除）。
 */

export {
  esc, renderMarkdown, scrollBottom, msgsEl, ts, fmtThreadStamp,
} from './markdown.js';

export {
  setAgentAvatar, agentAvatar, clearMsgs, showEmptyState,
  appendUserMsg, appendThreadMarker, appendProactiveBanner, appendAssistantMsg,
} from './bubbles.js';

export {
  appendSpeakStream, replaceOutlineSlot,
} from './speak_stream.js';

export { setTitleBarTyping, showSpeakTurnTyping } from './typing.js';
