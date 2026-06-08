# Win7 + Tauri 2 兼容性

> 项目要在 Windows 7 上跑桌面应用。本章记录 2026-06 调研出的 **Tauri 2.1.1 矩阵 + CVE backport** 兼容方案,以及为什么走这条路。

---

## 1. 一句话结论

**`tauri = "=2.1.1"` 矩阵 + `[patch.crates-io]` 指向 fork(含 CVE-2026-42184 backport)是 Win7 + Tauri 2.x 下唯一可行的兼容点**。Cargo.lock 必须 commit,CI 用 `--locked`。

---

## 2. 死锁地图(为什么不能简单升级)

```
Win7 ──需要──> Rust 1.77.2
                  │
                  ↓ 不支持
              edition2024  ←──需要── toml 0.9+ / serde_spanned 1.x
                                          ↑
                                       依赖
                                          │
                          tauri-utils ≥ 2.7  ←── 直接依赖于
                                          │
                              tauri ≥ 2.8 + tauri-build ≥ 2.3
```

**核心约束**:

- Win7 兼容必须 Rust **1.77.2**(1.78+ 移除 Win7 一级支持)
- Rust 1.77.2 不支持 Rust 2024 edition(2024 edition 在 Rust 1.85 才 stabilize)
- 多个 transitive crate(`toml 0.9+`、`serde_spanned 1.x`、`toml_parser 1.x` 等)需要 edition2024
- Tauri 2.8.0(2025-08-18, PR #13784)开始,`tauri-utils` 直接依赖 `toml 0.9` → 整套不可用

详细传递依赖污染路径见 [§5 失败试验记录](#5-失败试验记录)。

---

## 3. 突破方案:Tauri 2.1.1 矩阵

### 3.1 src-tauri/Cargo.toml 关键约束

```toml
[build-dependencies]
# 严格上限 < 2.4.1 触发 cargo 版本统一,阻止 tauri-winres → embed-resource 3.x → toml 1.0
tauri-build = "=2.0.3"
embed-resource = ">=2.1, <2.4.1"

[dependencies]
# 七个 tauri-* crate 必须严格同期 pin,任何 ^ resolver 都会拉到 toml 1.0
tauri              = "=2.1.1"
tauri-utils        = "=2.1.0"    # ⚠️ 不是 2.1.1,匹配 v2.1.1 tag 时 monorepo 内版本
tauri-runtime      = "=2.2.0"    # ⚠️ 防 trait 漂移(2.3 给 WindowDispatch 加 badge/overlay)
tauri-runtime-wry  = "=2.2.0"    # ⚠️ 防 webview2-com 多版本(2.3 用 webview2-com 0.34)

# uuid 1.13+ → getrandom 0.3 → wasip2 (Rust 1.87+); 锁 <1.13 保留 getrandom 0.2.x
uuid = ">=1.0, <1.13"

# 防 edition2024 链
hashbrown   = ">=0.14, <0.15"   # 0.15+ 要 edition2024
ahash       = ">=0.8,  <0.8.12" # 0.8.12+ 用 hashbrown 0.15+
indexmap    = ">=1.9,  <2.3"    # 2.3+ 用 hashbrown 0.15+
ignore      = ">=0.4,  <0.4.23" # 后续版本要 edition2024
globset     = ">=0.4,  <0.4.16" # 同上
chrono      = ">=0.4,  <0.4.39"
tokio       = ">=1,    <1.39"

[patch.crates-io]
# CVE-2026-42184 backport,见 §4
tauri              = { git = "https://github.com/oneMuggle/tauri", branch = "v2.1.1-win7-cve-patched" }
tauri-utils        = { git = "https://github.com/oneMuggle/tauri", branch = "v2.1.1-win7-cve-patched" }
tauri-runtime      = { git = "https://github.com/oneMuggle/tauri", branch = "v2.1.1-win7-cve-patched" }
tauri-runtime-wry  = { git = "https://github.com/oneMuggle/tauri", branch = "v2.1.1-win7-cve-patched" }
tauri-build        = { git = "https://github.com/oneMuggle/tauri", branch = "v2.1.1-win7-cve-patched" }
tauri-macros       = { git = "https://github.com/oneMuggle/tauri", branch = "v2.1.1-win7-cve-patched" }
tauri-codegen      = { git = "https://github.com/oneMuggle/tauri", branch = "v2.1.1-win7-cve-patched" }
```

### 3.1.b package.json 必须同步锁 npm 端 Tauri 包

Tauri CLI 在 `npx tauri build` 启动时会做 **major.minor 一致性校验**,不通过会直接 fail:

```
Found version mismatched Tauri packages. Make sure the NPM package and Rust crate
versions are on the same major/minor releases:
  tauri (v2.1.1) : @tauri-apps/api (v2.11.0)
```

所以 `package.json` 必须把 `@tauri-apps/api` 和 `@tauri-apps/cli` 也锁到 **2.1.x**:

```jsonc
{
  "dependencies": {
    "@tauri-apps/api": "=2.1.0",   // ⚠️ npm 2.1.x 只有 2.1.0,没有 2.1.1
  },
  "devDependencies": {
    "@tauri-apps/cli": "=2.1.0",   // (同上)
  }
}
```

**重要差异**:
- Rust Cargo.toml 锁 `tauri = "=2.1.1"`(fork 的 v2.1.1 tag 是 2.1.1)
- npm registry 上 `@tauri-apps/cli` 的 2.1.x 系列**只有 2.1.0**,**没有 2.1.1**
- Tauri CLI 的校验比较 **major.minor**(忽略 patch),所以 cli 2.1.0 + Rust 2.1.1 都通过

修改后用 `npm install --package-lock-only` 重新 sync `package-lock.json`,然后 commit。

### 3.2 .gitignore 必须删除 `Cargo.lock`

```diff
- # Rust / Cargo
- target/
- Cargo.lock
+ # Rust / Cargo
+ target/
+ # 注: Cargo.lock 必须 commit (应用程序,非库)
+ # - CI 用 --locked 严格按此 lock 编译
+ # - Tauri 2.1.1 + Win7 + Rust 1.77.2 依赖图脆弱,lock 是唯一锚点
```

原因:Rust 1.77.2 的 Cargo **不支持 MSRV-aware resolver**(Cargo 1.84+ 才有)。CI 上如果让它重新解析,会拉到 edition2024 包。必须用本地 Rust 1.84+ 的 MSRV-aware resolver 生成 lock,commit,然后 CI 用 `--locked` 严格按 lock 编译。

### 3.3 release.yml 关键 step

```yaml
- name: 安装 Rust (Win7 兼容版本)
  uses: dtolnay/rust-toolchain@1.77.2

- name: 编译 Rust Release
  run: cargo build --release --locked --target x86_64-pc-windows-msvc
  working-directory: src-tauri
```

**不要**加 `cargo update --precise` 步骤——会触发 resolver 重新解析,把 edition2024 包拉进来。

---

## 4. CVE-2026-42184 backport(D2)

### 4.1 漏洞

- **GHSA-7gmj-67g7-phm9**(CVSS v4 = 6.1, medium),公开于 2026-05-06
- **影响**:Tauri `>= 2.0, <= 2.11.0` 范围内,`http://app.evil.com/` 可冒充 `http://app.localhost/`,绕过 ACL 调用未受保护的自定义命令(应用未配置 `AppManifest` 时)
- **上游修复**:PR #15266,merge commit `1b26769f92b54b158777a35a7f548f870f4e7901`,进入 2.11.1
- **本项目**:用 Tauri 2.1.1,无法走升级路径,走 fork + cherry-pick backport

### 4.2 实施步骤

```bash
# 1. fork
gh repo fork tauri-apps/tauri --clone=false --remote=false

# 2. shallow clone fork (只需 tag,38MB)
git clone --depth 1 --branch tauri-v2.1.1 --single-branch \
  git@github.com:oneMuggle/tauri.git /tmp/tauri-fork

# 3. 创建 patched branch + 从 upstream fetch CVE commit
cd /tmp/tauri-fork
git remote add upstream https://github.com/tauri-apps/tauri.git
git checkout -b v2.1.1-win7-cve-patched
git fetch upstream 1b26769f92b54b158777a35a7f548f870f4e7901 --depth 50

# 4. cherry-pick (有 2 处冲突)
git cherry-pick 1b26769f92b54b158777a35a7f548f870f4e7901
# 冲突 1: crates/tauri/src/webview/mod.rs 核心 1 行 (保留 patch 版本: `|| !is_local`)
# 冲突 2: 测试代码 (丢弃 patch 测试,因为 mock API / set_simple_fullscreen 在 v2.1.1 不存在)
git add crates/tauri/src/webview/mod.rs
GIT_EDITOR=true git cherry-pick --continue

# 5. push 到 fork
git push -u origin v2.1.1-win7-cve-patched
```

### 4.3 核心修复(crates/tauri/src/webview/mod.rs)

```rust
// CVE-2026-42184 backport from upstream commit 1b26769f92
// 增加 `|| !is_local` ACL 守卫
if (plugin_command.is_some() || has_app_acl_manifest || !is_local)
```

---

## 5. 失败试验记录

发版前 7 次失败 CI run 累积出来的教训:

| # | commit | 失败原因 | 根因 |
|---|--------|----------|------|
| 1 | `4c38285` | `egor-tensin/vs-setup` 仓库 404 | 第三方 action 仓库已删除 |
| 2 | `dfcccf5` | npm ci 失败 | Node 18 太老(vitest 4.x 要 20+) |
| 3 | `385cc57` | cargo update --precise 命令过时 | tempfile 不在依赖图、reqwest 多版本歧义 |
| 4 | `6135b69` | serde_spanned v1.1.1 要 edition2024 | cargo update 步骤触发 resolver 重新解析 |
| 5 | `34785f2` | `--locked` 报 lock 不同步 | Cargo.lock 没 commit,CI 现场生成时不匹配 |
| 6 | `32bc334` | webview2-com 多版本冲突 (E0308) | tauri-runtime-wry ^2.2 拉到 2.3.0 (用 webview2-com 0.34) |
| 7 | `0db08aa` | 成功 ✓ | (D1 通过) |
| 8 | `3e8e172` | 成功 ✓ | (D2 通过) |

---

## 6. 维护提醒

### 6.1 升级 Tauri 时

不要简单 `cargo update`。每次评估升级:

1. 在临时项目里 pin 新 tauri 版本,跑 `cargo generate-lockfile`
2. 检查输出中是否有 `requires Rust 1.85` 或 `+spec-1.1.0`(且**没有** `available: ...` 后缀)
3. 如有 → 该 crate 自身要 edition2024,无法用 Rust 1.77.2 编译
4. `cargo tree -i <crate> --target x86_64-pc-windows-msvc` 查谁拉的,看能否锁定到旧版本绕开

### 6.2 重新生成 Cargo.lock

必须用 Cargo 1.84+ 的 MSRV-aware resolver:

```bash
cd src-tauri
rm Cargo.lock
CARGO_RESOLVER_INCOMPATIBLE_RUST_VERSIONS=fallback cargo generate-lockfile
cargo check        # 本地验证
git add Cargo.lock
git commit
```

**禁止**用 Rust 1.77.2 的 cargo 直接 `cargo build` 生成 lock——它会拉 edition2024 包,然后在 1.77.2 上编译失败。

### 6.3 fork 上游 patch 维护

当 upstream Tauri 发布新版本(2.12+ 等)修复了新 CVE,需要评估是否 backport 到 `oneMuggle/tauri:v2.1.1-win7-cve-patched`:

```bash
cd /tmp/tauri-fork  # 或重新 clone
git fetch upstream <new-cve-commit>
git checkout v2.1.1-win7-cve-patched
git cherry-pick <new-cve-commit>
# 解决冲突, 同样原则: 保留核心修复, 丢弃 v2.1.1 不存在的 API 引用
git push
```

不需要改 sage 的 Cargo.toml(branch 引用不变),只需在 sage 里 `cargo update --precise <hash>` 强制取新 commit。

### 6.4 长期路径

Tauri 官方方向是砍 Win7:

- RFC #12550 "Drop Windows 7 support"(2025-01-28 起 open)
- Issue #13221 "feat: bump MSRV to 1.83"(2025-04-13 起 open)

且 **WebView2 Runtime 已不再发布 Win7 版本**,即使编译过,运行时 WebView 加载也可能失败(WebView2 v109 是 Win7 最后版本,2023-01 停止安全更新)。

**建议**:

- 与产品方确认 Win7 用户占比
- 若 < 5%,切到 Win10+ 最低,放弃本方案,升级到 Tauri 2.11+ 拿回所有 bug fix
- 若是长尾(工业/政企/医疗),接受本方案 + 5-10% 的额外维护成本

---

## 7. 参考

- 上游 PR #15266: https://github.com/tauri-apps/tauri/pull/15266
- CVE 公告: https://github.com/tauri-apps/tauri/security/advisories/GHSA-7gmj-67g7-phm9
- Fork branch: https://github.com/oneMuggle/tauri/tree/v2.1.1-win7-cve-patched
- MSRV-aware resolver(Cargo 1.84+): https://doc.rust-lang.org/cargo/reference/resolver.html#rust-version
