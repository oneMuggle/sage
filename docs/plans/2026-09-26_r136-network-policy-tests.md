# R136：网络访问策略领域模型单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；内网 Web 访问网络策略（ONLINE/INTRANET/
  OFFLINE 三模式）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`domain/network_policy.py`（206 行，出网准入的核心判定层：手写 hostname
提取、host 归一化、`*.` 通配匹配（后缀混淆防御）、pattern 校验、三模式
工具注册门、执行期 host 准入、TLS 豁免覆盖校验、from_config 强转）——
安全语义密度最高却零测试的纯领域模块。

## 覆盖矩阵（约 24 例）

1. `_extract_hostname`：标准 URL、带 fragment/query、userinfo、端口、
   IPv6 方括号、无 `://` → None、空 host → None；
2. `normalize_host`：去空白/小写/尾点；
3. `host_matches`：精确命中、`*.apex` 命中 apex 自身与任意层级子域、
   **后缀混淆**（evilcnki.net）不命中、大小写与尾点归一后比较；
4. `_validate_pattern`（经构造器触发）：空条目、中间 `*`、`*.a` 单段
   过宽 → ValueError；
5. 三模式注册门：search_enabled 仅 ONLINE、fetch_enabled 非 OFFLINE；
6. `check_host`：ONLINE 恒放行、OFFLINE 恒拒绝（气隙文案）、INTRANET
   命中白名单放行/未命中拒绝/URL 无 host 拒绝；
7. `allows_insecure_tls`：命中豁免 True、未命中 False、坏 URL False；
8. insecure_tls 未被 allowed_hosts 覆盖 → ValueError；
9. `from_config`：缺字段回退默认、非法 mode → ValueError、
   allowed_hosts 类型不对（dict/裸字符串/非字符串元素）→ TypeError；
10. frozen 不可变。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
