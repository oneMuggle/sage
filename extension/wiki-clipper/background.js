/* eslint-disable no-undef */  // chrome API + Readability.js + Turndown.js (loaded via script tags)

// Sage Wiki Clipper - Background Service Worker
// 处理扩展生命周期事件和跨标签页通信

// 扩展安装时
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === 'install') {
    console.log('Sage Wiki Clipper 已安装');
  }
});

// 监听来自 content script 的消息（如果需要跨标签页通信）
chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
  // 可以在这里处理跨标签页的消息
  // 例如：检查后端 API 是否可达
  if (request.action === 'checkApi') {
    checkApiStatus(request.apiUrl)
      .then((status) => sendResponse({ success: true, status }))
      .catch((error) => sendResponse({ success: false, error: error.message }));
    return true;
  }
  return false;
});

// 检查 API 状态
async function checkApiStatus(apiUrl) {
  const response = await fetch(`${apiUrl}/health`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  });

  if (!response.ok) {
    throw new Error(`API 不可达: ${response.status}`);
  }

  return await response.json();
}
