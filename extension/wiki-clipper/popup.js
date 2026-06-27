// Sage Wiki Clipper - Popup Script
// 处理用户交互：获取当前页面信息，发送到后端 API

const DEFAULT_API_URL = 'http://127.0.0.1:8765/api/v1';

// DOM 元素
const apiUrlInput = document.getElementById('apiUrl');
const projectPathInput = document.getElementById('projectPath');
const pageTitleInput = document.getElementById('pageTitle');
const pageUrlInput = document.getElementById('pageUrl');
const notesInput = document.getElementById('notes');
const autoIngestCheckbox = document.getElementById('autoIngest');
const clipButton = document.getElementById('clipButton');
const statusDiv = document.getElementById('status');

// 加载保存的设置
chrome.storage.local.get(['apiUrl', 'projectPath', 'autoIngest'], (result) => {
  if (result.apiUrl) apiUrlInput.value = result.apiUrl;
  else apiUrlInput.value = DEFAULT_API_URL;
  if (result.projectPath) projectPathInput.value = result.projectPath;
  if (result.autoIngest !== undefined) autoIngestCheckbox.checked = result.autoIngest;
});

// 获取当前标签页信息
chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  if (tabs && tabs[0]) {
    pageTitleInput.value = tabs[0].title || '';
    pageUrlInput.value = tabs[0].url || '';
  }
});

// 显示状态
function showStatus(message, type) {
  statusDiv.textContent = message;
  statusDiv.className = `status ${type}`;
  statusDiv.style.display = 'block';
}

// 保存设置
function saveSettings() {
  chrome.storage.local.set({
    apiUrl: apiUrlInput.value,
    projectPath: projectPathInput.value,
    autoIngest: autoIngestCheckbox.checked,
  });
}

// 提取页面内容（通过 content script）
async function extractPageContent() {
  return new Promise((resolve, reject) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (!tabs || !tabs[0]) {
        reject(new Error('无法获取当前标签页'));
        return;
      }

      chrome.tabs.sendMessage(tabs[0].id, { action: 'extractContent' }, (response) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        if (response && response.success) {
          resolve(response);
        } else {
          reject(new Error(response?.error || '内容提取失败'));
        }
      });
    });
  });
}

// 发送到后端 API
async function clipToWiki(content) {
  const apiUrl = apiUrlInput.value.trim();
  const projectPath = projectPathInput.value.trim();
  const title = pageTitleInput.value.trim();
  const url = pageUrlInput.value.trim();
  const notes = notesInput.value.trim();
  const autoIngest = autoIngestCheckbox.checked;

  if (!apiUrl) throw new Error('请填写 API URL');
  if (!projectPath) throw new Error('请填写项目路径');
  if (!title) throw new Error('请填写页面标题');

  // 构建请求体
  const body = {
    title,
    url,
    content: content.markdown,
    project_path: projectPath,
    notes,
    auto_ingest: autoIngest,
  };

  const response = await fetch(`${apiUrl}/wiki/clip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`API 错误: ${response.status} - ${error}`);
  }

  return await response.json();
}

// 点击保存按钮
clipButton.addEventListener('click', async () => {
  clipButton.disabled = true;
  showStatus('正在提取页面内容...', 'info');

  try {
    // 保存设置
    saveSettings();

    // 提取内容
    const content = await extractPageContent();
    showStatus('正在保存到 Wiki...', 'info');

    // 发送到后端
    const result = await clipToWiki(content);

    showStatus(`✅ 保存成功！Wiki 页面: ${result.wiki_page_path || '已创建'}`, 'success');
  } catch (error) {
    showStatus(`❌ 错误: ${error.message}`, 'error');
  } finally {
    clipButton.disabled = false;
  }
});
