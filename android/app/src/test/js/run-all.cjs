// 顺序运行全部页面桥离线回归；任一用例失败时 process.exitCode 非 0。
// 供 npm test 与 Gradle 任务 :app:bridgeJsTest 共用。
'use strict';
require('./page-bridge.test.cjs');
require('./rename-bridge.test.cjs');
require('./archive-bridge.test.cjs');
