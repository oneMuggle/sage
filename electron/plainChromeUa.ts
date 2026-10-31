/**
 * 去掉 Electron 宿主指纹，归一为等价纯 Chrome UA。
 *
 * Electron 会把宿主 app 的 package.json name/version 拼进每个窗口的 UA
 * （… <appName>/<appVersion> Chrome/<v> Electron/<v> …）——常驻自动化特征，
 * 会压低 reCAPTCHA 评分并暴露桌面端身份。内置 Agent 浏览器与 arena token
 * 窗口共用同一口径（P4 真实冒烟已验证有效）。
 */
export function plainChromeUa(ua: string): string {
  return ua
    .replace(/\s+\S+\/\S+(?=\s+Chrome\/)/, '') // 宿主 app name/version token
    .replace(/\s+Electron\/\S+/, ''); // Electron token
}
