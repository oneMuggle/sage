/**
 * assistant 占位消息的 content 哨兵值。
 *
 * 发送后、首个 token 到达前，useChat 以该值占位（useChat.ts）。Message 组件
 * 检测到「流式中 + content 等于哨兵值」时渲染 shimmer 骨架而非 markdown 文本，
 * 避免「🤔 思考中…」以静态文本形式出现。agent 中间态文案（思考/调用工具等）
 * 会覆盖占位值，覆盖后自然回退 markdown 渲染。
 */
export const THINKING_PLACEHOLDER = '🤔 思考中…';
