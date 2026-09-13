/**
 * features/speak_pipeline_stub.js — pipeline 固定为 request_driven。
 *
 * 旧的 speak_responder 选择器已退役（服务端唯一支持 request_driven）；
 * 设置页 Soul tab 的同步调用保留为空实现以维持 UI 无感。
 */

export function syncSpeakResponderSetting() {
  /* pipeline 已固定，无需同步 */
}

export function getSpeakResponder() {
  return 'request_driven';
}
