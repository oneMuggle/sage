import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: false });
const page = await browser.newPage();

try {
  // 导航到 /chat
  await page.goto('http://localhost:1420/chat');
  await page.waitForLoadState('networkidle');
  console.log('✅ 已导航到 /chat');
  
  // 截图
  await page.screenshot({ path: 'nav-history-1-chat.png' });
  console.log('📸 截图：nav-history-1-chat.png');
  
  // 点击设置链接
  const settingsLink = page.getByRole('link', { name: /设置/ });
  if (await settingsLink.isVisible()) {
    await settingsLink.click();
    await page.waitForURL(/\/settings/);
    console.log('✅ 已导航到 /settings');
    await page.screenshot({ path: 'nav-history-2-settings.png' });
  }
  
  // 检查后退按钮
  const backBtn = page.getByLabel('后退');
  const isBackDisabled = await backBtn.isDisabled();
  console.log(`后退按钮 disabled: ${isBackDisabled}`);
  
  if (!isBackDisabled) {
    await backBtn.click();
    await page.waitForURL(/\/chat/);
    console.log('✅ 点击后退，已导航回 /chat');
    await page.screenshot({ path: 'nav-history-3-back.png' });
  }
  
  // 检查前进按钮
  const forwardBtn = page.getByLabel('前进');
  const isForwardDisabled = await forwardBtn.isDisabled();
  console.log(`前进按钮 disabled: ${isForwardDisabled}`);
  
  if (!isForwardDisabled) {
    await forwardBtn.click();
    await page.waitForURL(/\/settings/);
    console.log('✅ 点击前进，已导航到 /settings');
    await page.screenshot({ path: 'nav-history-4-forward.png' });
  }
  
  console.log('✅ 测试完成');
} catch (error) {
  console.error('❌ 测试失败:', error.message);
  await page.screenshot({ path: 'nav-history-error.png' });
} finally {
  await browser.close();
}
