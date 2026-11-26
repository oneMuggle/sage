# 文献下载中间页主机回退（xueshu789 oversea→kns）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) 或 superpowers:executing-plans 按任务执行；步骤用 `- [ ]` 复选框跟踪。

**Goal:** 修复 xueshu789 文献「下载」断链：站点下载中间页把最终地址写死为 `oversea.cnki.net`（国内库内容 404），需要 profile 驱动的「中间页识别 + 主机回退」下载路径，使文献调研流水线能真实下载 PDF。

**Architecture:** 新增站点 profile 可选的 `pdf.interstitial` 声明（识别中间页 URL、回退主机列表、等待时序）；在 `backend/literature/search.py::download_pdf` 增加一条「读取入口 href → 新标签打开 → 等中间页跳转 → 按回退主机重写 URL → 导航触发下载 → 校验 PDF」的路径，原「点击入口」路径保留。为拿到完整 `a.downloadlink` href（含 `&ddata=`，快照里被截断到 200 字符），给 `browser_interact` 增加只读动作 `attr`。站点差异全部留在 profile，不进代码。

**Tech Stack:** Python 3.10（`sage-backend` conda 环境，代码保持 py38 兼容）、pytest、FastAPI 工具层、Electron 21 嵌入浏览器桥（本方案不改 Electron 代码）。

**Spec（根因与真机证据，2026-11-26 实测）：**
- 点击结果行 `a.downloadlink`（target=_blank）→ `www.xueshu789.cc/doDownload?...&ddata=...` **301** → `/doDownload/` 返回「文献下载中」HTML 中间页，**约 2s 后** JS `window.location = downurl`。
- 中间页把 `downurl` 写死为 `https://oversea.cnki.net/docdown/fulltext/download?q=...&invoice=...`；国内库（CJFQ）内容在该网关返回 CNKI 404「页面不存在」。与登录态/Referer/UA/cookie 无关（curl 复放排除）。
- 同一 token 换成 `kns.cnki.net` → `200 application/pdf`：浏览器内重写主机后真实落盘 1,688,310B、`%PDF-1.6`、题名匹配。
- 弹窗由 `window.open` 打开，**不在桥注册表**（`Target.getTargets` 看不到），因此新方案不使用「点击后找弹窗」，而是用 `browser_tabs create` 主动开**工具可见**的标签页。

---

## Global Constraints

- 后端命令一律用 `/home/fz/anaconda3/envs/sage-backend/bin/python`；禁止污染 conda 环境。
- 代码保持 **py38 语法兼容**（`scripts/check_py38_compat.py` 门禁）：不用 `match`、不用 `X | Y` 运行期注解、`isinstance` 不用 `(A, B)` tuple 写法（ruff UP038）。
- ruff 提交前必跑：中文注释易触发 ERA001，字符串双引号（Q000）。
- 站点逻辑（域名、选择器、回退主机）**只出现在 profile YAML 与 skill 文档**，不得写进 backend 代码。
- `architecture-baseline.json` 棘轮「只升不降」：`backend/tools/browser_tool.py` 当前 4216 行 / 基线 4217，本方案会让它增长，需同步把基线改成实际行数（附理由）。
- 提交信息用 Conventional Commits（`fix:` / `feat:` / `test:` / `docs:`）。
- 测试在 worktree 内、用 `sage-backend` 解释器运行。

---

## 文件结构（改动清单）

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `backend/literature/models.py` | 修改 | 新增 `PdfInterstitialSpec`；`PdfSpec.interstitial`；`_parse_pdf` 解析/校验 |
| `backend/literature/search.py` | 修改 | `download_pdf` 新增 interstitial 路径 + URL 候选/标签页发现/清理辅助 |
| `backend/literature/sage_driver.py` | 修改 | `element_attr` / `tabs` / `open_tab` / `focus_tab` / `close_tab` |
| `backend/tools/browser_tool.py` | 修改 | `browser_interact` 新增只读动作 `attr` |
| `docs/templates/literature-sites/xueshu789.yaml` | 修改 | 增加 `pdf.interstitial` 段 + 版本/备注 |
| `docs/templates/literature-sites/README.md` | 修改 | 文档化 `pdf.interstitial` 字段 |
| `backend/literature/README.md` | 修改 | §3.4 下载流程补 interstitial 说明 |
| `docs/technical/164-literature-research-subsystem.md` | 修改 | profile 字段表与下载流程小节同步 |
| `backend/skills/skill_md/shipped/literature-research/SKILL.md` | 修改 | 下载步骤改用 `download_pdf` + 行级 `entry_selector` |
| `backend/tests/unit/test_literature_site_profiles.py` | 修改 | interstitial 解析/校验测试 |
| `backend/tests/unit/test_literature_pipeline.py` | 修改 | interstitial 下载路径 + 驱动方法测试 |
| `backend/tests/unit/test_browser_tool.py` | 修改 | `attr` 动作测试 |
| `architecture-baseline.json` | 修改 | `browser_tool.py` 行数基线更新 |

---

### Task 1: Profile 模型 — `pdf.interstitial`

**Files:**
- Modify: `backend/literature/models.py`（`PdfSpec` 附近 + `_parse_pdf`）
- Test: `backend/tests/unit/test_literature_site_profiles.py`

**Interfaces:**
- Produces:
  - `PdfInterstitialSpec(url_contains: Tuple[str, ...] = (), host_fallbacks: Tuple[str, ...] = (), tab_timeout_s: float = 6.0, sleep_after_open_s: float = 2.5, attempt_timeout_s: float = 15.0)`
  - `PdfSpec.interstitial: Optional[PdfInterstitialSpec] = None`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/unit/test_literature_site_profiles.py` 的 `TestProfileModel` 类中追加：

```python
    def test_pdf_interstitial_parses(self):
        raw = _raw_profile()
        raw["pdf"]["interstitial"] = {
            "url_contains": ["cnki.net/docdown"],
            "host_fallbacks": ["kns.cnki.net"],
            "tab_timeout_s": 8,
            "sleep_after_open_s": 3,
            "attempt_timeout_s": 20,
        }
        profile = profile_from_dict(raw)
        inter = profile.pdf.interstitial
        assert inter is not None
        assert inter.url_contains == ("cnki.net/docdown",)
        assert inter.host_fallbacks == ("kns.cnki.net",)
        assert inter.tab_timeout_s == 8.0
        assert inter.sleep_after_open_s == 3.0
        assert inter.attempt_timeout_s == 20.0

    def test_pdf_interstitial_defaults(self):
        raw = _raw_profile()
        raw["pdf"]["interstitial"] = {"url_contains": ["cnki.net/docdown"]}
        inter = profile_from_dict(raw).pdf.interstitial
        assert inter.host_fallbacks == ()
        assert inter.tab_timeout_s == 6.0
        assert inter.sleep_after_open_s == 2.5
        assert inter.attempt_timeout_s == 15.0

    def test_pdf_interstitial_requires_url_contains(self):
        raw = _raw_profile()
        raw["pdf"]["interstitial"] = {"host_fallbacks": ["kns.cnki.net"]}
        with pytest.raises(SiteProfileError, match="url_contains"):
            profile_from_dict(raw)

    def test_pdf_interstitial_absent_by_default(self):
        assert profile_from_dict(_raw_profile()).pdf.interstitial is None
```

- [ ] **Step 2: 跑测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_site_profiles.py -q -k interstitial
```

预期：4 个用例 FAIL（`PdfSpec` 无 `interstitial` 属性 / 解析不识别）。

- [ ] **Step 3: 最小实现**

`backend/literature/models.py`，在 `PdfSpec` 定义之前新增 dataclass，并给 `PdfSpec` 加字段：

```python
@dataclass(frozen=True)
class PdfInterstitialSpec:
    """下载中间页声明：入口先落到「准备中」页、随后再跳最终下载地址的站点。

    ``url_contains`` 用于在标签页 URL 中识别中间页/最终跳转地址；
    ``host_fallbacks`` 是在最终地址上依次替换主机的回退列表（原域放最后兜底）。
    """

    url_contains: Tuple[str, ...] = ()
    host_fallbacks: Tuple[str, ...] = ()
    tab_timeout_s: float = 6.0
    sleep_after_open_s: float = 2.5
    attempt_timeout_s: float = 15.0
```

```python
@dataclass(frozen=True)
class PdfSpec:
    entry_selector: Optional[str] = None
    entry_text: Optional[str] = None
    forbid: Tuple[str, ...] = ("CAJ",)
    magic: str = "%PDF-"
    title_match: bool = True
    post_click_wait_s: float = 0.0
    interstitial: Optional[PdfInterstitialSpec] = None
    note: Optional[str] = None
```

在 `_parse_pdf` 之前新增解析函数，并在 `_parse_pdf` 的返回里接上：

```python
def _parse_pdf_interstitial(raw: Any) -> Optional[PdfInterstitialSpec]:
    if raw is None:
        return None
    data = _require_dict(raw, "pdf.interstitial")
    url_contains = _str_tuple(data.get("url_contains"), "pdf.interstitial.url_contains")
    if not url_contains:
        raise SiteProfileError("pdf.interstitial.url_contains 不能为空")
    return PdfInterstitialSpec(
        url_contains=url_contains,
        host_fallbacks=_str_tuple(
            data.get("host_fallbacks"), "pdf.interstitial.host_fallbacks"
        ),
        tab_timeout_s=float(data.get("tab_timeout_s", 6.0)),
        sleep_after_open_s=float(data.get("sleep_after_open_s", 2.5)),
        attempt_timeout_s=float(data.get("attempt_timeout_s", 15.0)),
    )
```

```python
    return PdfSpec(
        entry_selector=entry_selector,
        entry_text=entry_text,
        forbid=_str_tuple(data.get("forbid"), "pdf.forbid") or ("CAJ",),
        magic=_require_str(validate.get("magic"), "pdf.validate.magic") or "%PDF-",
        title_match=bool(validate.get("title_match", True)),
        post_click_wait_s=float(data.get("post_click_wait_s", 0.0)),
        interstitial=_parse_pdf_interstitial(data.get("interstitial")),
        note=_optional_str(data.get("note"), "pdf.note"),
    )
```

- [ ] **Step 4: 跑测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_site_profiles.py -q
```

预期：全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/literature/models.py backend/tests/unit/test_literature_site_profiles.py
git commit -m "feat(literature): profile 支持 pdf.interstitial 中间页声明"
```

---

### Task 2: `browser_interact` 新增只读动作 `attr`

**Files:**
- Modify: `backend/tools/browser_tool.py`（`_VALID_ACTIONS`、schema、`_interact_arg_error`、`_build_interact_expression`、`execute` 签名与调用点、JS 辅助）
- Test: `backend/tests/unit/test_browser_tool.py`

**Interfaces:**
- Produces: `browser_interact(action="attr", selector="...", name="href")` → `ToolResult.content["info"]` 为属性值（字符串，截断 4000 字符）；元素不存在/属性不存在/选择器非法时 `success=False`。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/unit/test_browser_tool.py` 的交互测试区追加：

```python
def test_interact_attr_returns_attribute_value(stubbed):
    stubbed.results.append(
        {
            "result": {
                "value": {
                    "ok": True,
                    "info": "https://www.xueshu789.cc/doDownload?url=x&ddata=y",
                }
            }
        }
    )
    result = _tool(BrowserInteractTool).execute(
        action="attr", selector="a.downloadlink", name="href", browser_id="b1"
    )
    assert result.success is True
    assert result.content["info"].startswith("https://www.xueshu789.cc/doDownload")
    expression = stubbed.calls[0]["params"]["expression"]
    assert "getAttribute" in expression
    assert "href" in expression


def test_interact_attr_defaults_to_href(stubbed):
    stubbed.results.append({"result": {"value": {"ok": True, "info": "https://x/a"}}})
    result = _tool(BrowserInteractTool).execute(
        action="attr", selector="a.link", browser_id="b1"
    )
    assert result.success is True
    expression = stubbed.calls[0]["params"]["expression"]
    assert "href" in expression


def test_interact_attr_requires_locator(stubbed):
    result = _tool(BrowserInteractTool).execute(action="attr", browser_id="b1")
    assert result.success is False
    assert "attr 需要 ref 或 selector" in result.error
```

- [ ] **Step 2: 跑测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_browser_tool.py -q -k "interact_attr"
```

预期：FAIL（`attr` 不在 `_VALID_ACTIONS`）。

- [ ] **Step 3: 最小实现**

3a. `_VALID_ACTIONS` 追加 `"attr"`：

```python
_VALID_ACTIONS = (
    "click",
    "type",
    "press",
    "scroll",
    "select",
    "hover",
    "check",
    "uncheck",
    "upload",
    "attr",
)
```

3b. `_interact_arg_error` 增加分支（放在 `press` 之前均可）：

```python
    elif action == "attr":
        if not located:
            error = "attr 需要 ref 或 selector"
```

3c. 新增 JS 辅助函数（放在 `_js_type_element` 附近）：

```python
def _js_attr_element(name: str) -> str:
    return (
        "(function(){"
        f"var next={json.dumps(name)};"
        "if(!el.getAttribute){return{ok:false,info:'no-attribute-api'};}"
        "var v=el.getAttribute(next);"
        "if(v===null){return{ok:false,info:'attribute-not-found: '+next};}"
        "return{ok:true,info:String(v).slice(0,4000)};"
        "})()"
    )


def _js_attr_selector(selector: str, name: str) -> str:
    return (
        "(function(){"
        f"var sel={json.dumps(selector)};"
        "var el=null;"
        "try{el=document.querySelector(sel);}catch(e){return{ok:false,info:'invalid-selector'};}"
        "if(!el){return{ok:false,info:'not-found: '+sel};}"
        f"var next={json.dumps(name)};"
        "var v=el.getAttribute(next);"
        "if(v===null){return{ok:false,info:'attribute-not-found: '+next};}"
        "return{ok:true,info:String(v).slice(0,4000)};"
        "})()"
    )
```

3d. `_build_interact_expression` 增加参数与分支（签名加 `name: str`；在最前面加）：

```python
    if action == "attr":
        expression = (
            build_ref_expression(_js_attr_element(name), ref)
            if ref
            else _js_attr_selector(selector, name)
        )
        return _expression_with_page_info(expression)
```

3e. schema：`enum` 追加 `"attr"`；新增参数：

```python
                    "name": {
                        "type": "string",
                        "description": "attr 动作要读取的元素属性名（默认 href）",
                    },
```

3f. `execute` 签名加 `name: str = ""`；进入校验前归一化：

```python
        name = (name or "").strip() or "href"
```

并在 `_build_interact_expression(...)` 调用点补传 `name=name`。

- [ ] **Step 4: 跑测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_browser_tool.py -q
```

预期：全部 PASS（含既有用例）。

- [ ] **Step 5: Commit**

```bash
git add backend/tools/browser_tool.py backend/tests/unit/test_browser_tool.py
git commit -m "feat(browser): browser_interact 支持只读 attr 动作读取元素属性"
```

---

### Task 3: SageToolDriver 扩展（attr / tabs / 打开、切换、关闭标签）

**Files:**
- Modify: `backend/literature/sage_driver.py`
- Test: `backend/tests/unit/test_literature_pipeline.py`（`_FakeCall` 已有）

**Interfaces:**
- Consumes: Task 2 的 `browser_interact(action="attr")`；既有 `browser_tabs` 工具（action=list/create/switch/close）。
- Produces（供 Task 4 使用）：
  - `element_attr(selector: str, name: str = "href") -> str`
  - `tabs() -> List[Dict[str, Any]]`（元素含 `tab_id`/`url`/`title`/`active`）
  - `open_tab(url: str) -> str`（返回 tab_id，可能为 ""）
  - `focus_tab(tab_id: str) -> None`
  - `close_tab(tab_id: str) -> None`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/unit/test_literature_pipeline.py` 的 `TestSageDriver`（若无则新建类）中追加：

```python
class TestSageDriverTabs:
    def test_element_attr_reads_info(self):
        from backend.literature.sage_driver import SageToolDriver

        call = _FakeCall()
        call.responses["browser_interact"] = {
            "action": "attr",
            "info": "https://www.xueshu789.cc/doDownload?url=x&ddata=y",
        }
        driver = SageToolDriver(call)
        value = driver.element_attr("table tbody tr a.downloadlink")
        assert value.startswith("https://www.xueshu789.cc/doDownload")
        assert call.calls[-1] == (
            "browser_interact",
            {
                "action": "attr",
                "selector": "table tbody tr a.downloadlink",
                "name": "href",
            },
        )

    def test_tabs_lists_dicts(self):
        from backend.literature.sage_driver import SageToolDriver

        call = _FakeCall()
        call.responses["browser_tabs"] = {
            "tabs": [
                {"tab_id": "t1", "url": "https://oversea.cnki.net/docdown?q=1", "active": True},
                "bad-entry",
            ]
        }
        driver = SageToolDriver(call)
        tabs = driver.tabs()
        assert tabs == [{"tab_id": "t1", "url": "https://oversea.cnki.net/docdown?q=1", "active": True}]

    def test_open_focus_close_tab(self):
        from backend.literature.sage_driver import SageToolDriver

        call = _FakeCall()
        call.responses["browser_tabs"] = {"tab_id": "t9"}
        driver = SageToolDriver(call)
        assert driver.open_tab("https://a/do") == "t9"
        assert call.calls[-1] == ("browser_tabs", {"action": "create", "url": "https://a/do"})
        driver.focus_tab("t9")
        assert call.calls[-1] == ("browser_tabs", {"action": "switch", "tab_id": "t9"})
        driver.close_tab("t9")
        assert call.calls[-1] == ("browser_tabs", {"action": "close", "tab_id": "t9"})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_pipeline.py -q -k "TestSageDriverTabs"
```

预期：FAIL（方法不存在）。

- [ ] **Step 3: 最小实现**

`backend/literature/sage_driver.py` 在 `wait_download` 之前追加：

```python
    def element_attr(self, selector: str, name: str = "href") -> str:
        """读取元素属性（如下载链接的完整 href）。"""
        self._ensure_browser()
        data = self._as_dict(
            self._tool("browser_interact", action="attr", selector=selector, name=name)
        )
        return str(data.get("info") or "")

    def tabs(self) -> List[Dict[str, Any]]:
        data = self._as_dict(self._tool("browser_tabs", action="list"))
        return [tab for tab in (data.get("tabs") or []) if isinstance(tab, dict)]

    def open_tab(self, url: str) -> str:
        data = self._as_dict(self._tool("browser_tabs", action="create", url=url))
        self._browser_ready = True
        return str(data.get("tab_id") or "")

    def focus_tab(self, tab_id: str) -> None:
        if tab_id:
            self._tool("browser_tabs", action="switch", tab_id=tab_id)

    def close_tab(self, tab_id: str) -> None:
        if tab_id:
            self._tool("browser_tabs", action="close", tab_id=tab_id)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_pipeline.py -q -k "TestSageDriver"
```

- [ ] **Step 5: Commit**

```bash
git add backend/literature/sage_driver.py backend/tests/unit/test_literature_pipeline.py
git commit -m "feat(literature): 驱动新增 attr/标签页能力"
```

---

### Task 4: `download_pdf` 中间页主机回退路径

**Files:**
- Modify: `backend/literature/search.py`
- Test: `backend/tests/unit/test_literature_pipeline.py`

**Interfaces:**
- Consumes: Task 1 `PdfInterstitialSpec`；Task 3 驱动方法。
- Produces:
  - `download_pdf(profile, driver, expected_title, dest_dir, timeout_s=60, *, entry_url="", entry_selector="") -> DownloadResult`
  - 内部辅助：`_candidate_download_urls(url, hosts) -> List[str]`（先回退主机、后原域）、`_find_interstitial_tab(driver, inter, timeout_s)`、`_close_tab_quietly(driver, tab_id)`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/unit/test_literature_pipeline.py` 的 `TestBrowserSearch` 中追加（并在文件里定义 `_InterstitialDriver`）：

```python
class _InterstitialDriver(_FakeDriver):
    def __init__(self):
        super().__init__()
        self.attrs = []
        self.opened = []
        self.focused = []
        self.closed = []
        self.tab_sleeps = []
        self.navigations = []
        self.entry_href = "https://www.xueshu789.cc/doDownload?url=x&ddata=y"
        self.tabs_state = [
            {"tab_id": "t1", "url": "https://oversea.cnki.net/docdown/fulltext/download?q=abc", "active": True}
        ]
        self.navigate_errors = {}

    def element_attr(self, selector, name="href"):
        self.attrs.append((selector, name))
        return self.entry_href

    def open_tab(self, url):
        self.opened.append(url)
        return "t1"

    def sleep(self, seconds):
        self.tab_sleeps.append(seconds)

    def tabs(self):
        return self.tabs_state

    def focus_tab(self, tab_id):
        self.focused.append(tab_id)

    def close_tab(self, tab_id):
        self.closed.append(tab_id)

    def navigate(self, url, wait_for=""):
        self.navigations.append(url)
        if url in self.navigate_errors:
            raise RuntimeError(self.navigate_errors[url])
        return url
```

```python
    def _interstitial_profile(self):
        from backend.literature.models import profile_from_dict

        raw = _raw_profile()
        raw["pdf"]["interstitial"] = {
            "url_contains": ["cnki.net/docdown"],
            "host_fallbacks": ["kns.cnki.net"],
        }
        return profile_from_dict(raw)

    def test_download_interstitial_rewrites_host_and_validates(self, tmp_path):
        from backend.literature.search import download_pdf

        driver = _InterstitialDriver()
        pdf = tmp_path / "示例论文.pdf"
        pdf.write_bytes(b"%PDF-1.6\nfake")
        driver.download_path = str(pdf)
        result = download_pdf(
            self._interstitial_profile(),
            driver,
            "示例论文",
            tmp_path,
            entry_selector="table tbody tr:nth-child(1) a.downloadlink",
        )
        assert result.ok is True, result.errors
        assert driver.attrs == [("table tbody tr:nth-child(1) a.downloadlink", "href")]
        assert driver.opened == ["https://www.xueshu789.cc/doDownload?url=x&ddata=y"]
        assert driver.focused == ["t1"]
        assert driver.navigations[0].startswith("https://kns.cnki.net/docdown/")
        assert "q=abc" in driver.navigations[0]
        assert driver.closed == ["t1"]
        assert driver.clicks == []

    def test_download_interstitial_tolerates_navigation_abort(self, tmp_path):
        from backend.literature.search import download_pdf

        driver = _InterstitialDriver()
        pdf = tmp_path / "示例论文.pdf"
        pdf.write_bytes(b"%PDF-1.6\nfake")
        driver.download_path = str(pdf)
        kns_url = "https://kns.cnki.net/docdown/fulltext/download?q=abc"
        driver.navigate_errors[kns_url] = "net::ERR_ABORTED"
        result = download_pdf(
            self._interstitial_profile(), driver, "示例论文", tmp_path
        )
        assert result.ok is True, result.errors

    def test_download_interstitial_without_tab_fails(self, tmp_path):
        from backend.literature.search import download_pdf

        driver = _InterstitialDriver()
        driver.tabs_state = []
        result = download_pdf(
            self._interstitial_profile(), driver, "示例论文", tmp_path
        )
        assert result.ok is False
        assert any("url_contains" in e for e in result.errors)

    def test_candidate_urls_order(self):
        from backend.literature.search import _candidate_download_urls

        urls = _candidate_download_urls(
            "https://oversea.cnki.net/docdown/x?q=1&invoice=2",
            ["kns.cnki.net", "kns.cnki.net", "alt.example"],
        )
        assert urls[0] == "https://kns.cnki.net/docdown/x?q=1&invoice=2"
        assert urls[1] == "https://alt.example/docdown/x?q=1&invoice=2"
        assert urls[2].startswith("https://oversea.cnki.net/docdown/x?q=1")
        assert len(urls) == 3
```

- [ ] **Step 2: 跑测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_pipeline.py -q -k "interstitial or candidate_urls"
```

预期：FAIL（`_candidate_download_urls` 不存在；`download_pdf` 忽略 interstitial）。

- [ ] **Step 3: 最小实现**

`backend/literature/search.py`：

3a. 头部 import 补 `time` 与 URL 工具：

```python
import time
from urllib.parse import urlsplit, urlunsplit
```

3b. `download_pdf` 签名与入口：

```python
def download_pdf(
    profile: SiteProfile,
    driver: BrowserDriver,
    expected_title: str,
    dest_dir: Path,
    timeout_s: float = 60,
    *,
    entry_url: str = "",
    entry_selector: str = "",
) -> DownloadResult:
    """下载并校验 PDF。

    站点声明了 ``pdf.interstitial`` 时走「中间页 + 主机回退」路径：
    读取入口 href → 新标签打开 → 等中间页跳转 → 按回退主机重写 URL 导航 →
    等下载完成；拿不到入口 URL 或驱动缺能力时回退到原「点击入口」路径。
    """
    if profile.pdf is None:
        return DownloadResult(None, False, ["站点未配置 pdf 下载"])
    if profile.pdf.interstitial is not None:
        result = _download_via_interstitial(
            profile,
            driver,
            expected_title,
            dest_dir,
            timeout_s,
            entry_url=entry_url,
            entry_selector=entry_selector,
        )
        if result is not None:
            return result
    target = profile.pdf.entry_selector or profile.pdf.entry_text
    if not target:
        return DownloadResult(None, False, ["站点未配置 PDF 入口"])
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if profile.pdf.entry_selector:
        driver.click(profile.pdf.entry_selector)
    else:
        driver.click_text(profile.pdf.entry_text or "")
    if profile.pdf.post_click_wait_s:
        driver.sleep(profile.pdf.post_click_wait_s)
    downloaded = driver.wait_download(timeout_s=timeout_s)
    if not downloaded:
        return DownloadResult(None, False, ["等待下载超时"])
    path = Path(downloaded)
    errors = validate_pdf(path, expected_title, profile.pdf.magic)
    if profile.pdf.forbid:
        for word in profile.pdf.forbid:
            if word.lower() in path.suffix.lower():
                errors.append(f"禁止的下载格式: {word}")
    return DownloadResult(str(path), not errors, errors)
```

3c. 新增辅助与路径函数（放在 `download_pdf` 上方）：

```python
def _candidate_download_urls(url: str, hosts: List[str]) -> List[str]:
    """按回退主机生成候选 URL（回退主机在前，原域最后）。"""
    parts = urlsplit(url)
    candidates: List[str] = []
    for host in hosts:
        host = str(host or "").strip()
        if not host:
            continue
        candidate = urlunsplit(
            (parts.scheme or "https", host, parts.path, parts.query, "")
        )
        if candidate not in candidates:
            candidates.append(candidate)
    original = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
    if original and original not in candidates:
        candidates.append(original)
    return candidates


def _find_interstitial_tab(
    driver: BrowserDriver, inter: Any, timeout_s: float
) -> Optional[dict]:
    deadline = time.monotonic() + max(0.0, timeout_s)
    while True:
        try:
            tabs = driver.tabs()
        except Exception:  # noqa: BLE001 — 驱动缺能力/失败按未发现处理
            return None
        for tab in tabs:
            url = str(tab.get("url") or "")
            if url and any(token in url for token in inter.url_contains):
                return tab
        if time.monotonic() >= deadline:
            return None
        driver.sleep(0.5)


def _close_tab_quietly(driver: BrowserDriver, tab_id: str) -> None:
    closer = getattr(driver, "close_tab", None)
    if closer is None or not tab_id:
        return
    try:
        closer(tab_id)
    except Exception:  # noqa: BLE001 — 清理失败不影响下载结果
        pass


def _download_via_interstitial(
    profile: SiteProfile,
    driver: BrowserDriver,
    expected_title: str,
    dest_dir: Path,
    timeout_s: float,
    *,
    entry_url: str,
    entry_selector: str,
) -> Optional[DownloadResult]:
    """中间页下载；返回 None 表示应回退到原点击路径。"""
    pdf = profile.pdf
    inter = pdf.interstitial if pdf is not None else None
    if inter is None:
        return None
    if not entry_url:
        selector = entry_selector or pdf.entry_selector or ""
        reader = getattr(driver, "element_attr", None)
        if not selector or reader is None:
            return None
        try:
            entry_url = reader(selector, "href")
        except Exception:  # noqa: BLE001 — 读取失败按回退处理
            return None
    opener = getattr(driver, "open_tab", None)
    if not entry_url or opener is None:
        return None
    tab_id = opener(entry_url)
    if inter.sleep_after_open_s:
        driver.sleep(inter.sleep_after_open_s)
    tab = _find_interstitial_tab(driver, inter, inter.tab_timeout_s)
    if tab is None:
        _close_tab_quietly(driver, tab_id)
        return DownloadResult(
            None,
            False,
            ["未发现下载中间页标签（检查 pdf.interstitial.url_contains）"],
        )
    target_tab = str(tab.get("tab_id") or tab_id or "")
    candidates = _candidate_download_urls(str(tab.get("url") or ""), list(inter.host_fallbacks))
    errors: List[str] = []
    for index, candidate in enumerate(candidates):
        if target_tab:
            driver.focus_tab(target_tab)
        try:
            driver.navigate(candidate)
        except Exception:  # noqa: BLE001 — 附件下载会中断导航（ERR_ABORTED），继续等下载
            pass
        last = index == len(candidates) - 1
        wait_s = timeout_s if last else min(timeout_s, inter.attempt_timeout_s)
        downloaded = driver.wait_download(timeout_s=wait_s)
        if not downloaded:
            errors.append(f"{candidate}: 等待下载超时")
            continue
        path = Path(downloaded)
        problems = validate_pdf(path, expected_title, pdf.magic)
        if pdf.forbid:
            for word in pdf.forbid:
                if word.lower() in path.suffix.lower():
                    problems.append(f"禁止的下载格式: {word}")
        if not problems:
            _close_tab_quietly(driver, target_tab)
            return DownloadResult(str(path), True)
        errors.extend(f"{candidate}: {problem}" for problem in problems)
    _close_tab_quietly(driver, target_tab)
    return DownloadResult(None, False, errors or ["下载失败"])
```

3d. 在 `BrowserDriver` Protocol 文档注释里补充可选能力说明（不加入 Protocol 方法，避免强制实现）：

```python
class BrowserDriver(Protocol):
    """浏览器驱动协议。

    可选能力（站点 profile 声明 ``pdf.interstitial`` 时需要）：
    ``element_attr(selector, name)``、``tabs()``、``open_tab(url)``、
    ``focus_tab(tab_id)``、``close_tab(tab_id)``。
    """
    ...
```

- [ ] **Step 4: 跑测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_pipeline.py -q
```

预期：全部 PASS（含既有 click 路径用例）。

- [ ] **Step 5: Commit**

```bash
git add backend/literature/search.py backend/tests/unit/test_literature_pipeline.py
git commit -m "feat(literature): download_pdf 支持中间页主机回退下载"
```

---

### Task 5: xueshu789 模板与文档同步

**Files:**
- Modify: `docs/templates/literature-sites/xueshu789.yaml`
- Modify: `docs/templates/literature-sites/README.md`
- Modify: `backend/literature/README.md`（§3.4）
- Modify: `docs/technical/164-literature-research-subsystem.md`（字段表 + §3.4）
- Test: `backend/tests/unit/test_literature_site_profiles.py`（如已有加载真实模板的用例，一并断言）

- [ ] **Step 1: 更新模板**

`docs/templates/literature-sites/xueshu789.yaml` 的 `pdf` 段追加：

```yaml
pdf:
  entry:
    selector: "a.downloadlink"
    text: 下载
  post_click_wait_s: 8
  # 下载中间页：doDownload 301 → /doDownload/ 「文献下载中」页，约 2s 后
  # JS 跳 downurl；该站把 downurl 主机写死为 oversea.cnki.net，国内库内容
  # 在海外网关 404。运行时按 host_fallbacks 先换 kns.cnki.net 再原域兜底。
  interstitial:
    url_contains:
      - "cnki.net/docdown"
    host_fallbacks:
      - "kns.cnki.net"
    tab_timeout_s: 6
    sleep_after_open_s: 2.5
    attempt_timeout_s: 15
  note: "必须点击 a.downloadlink 元素（完整 href 含 &ddata=）；不要用快照中截断的 URL 直连，否则 doDownload 报参数错误。中间页主机回退见 interstitial。"
  forbid:
    - CAJ
  validate:
    magic: "%PDF-"
    title_match: true
```

并把 `version: "0.3.1"` → `version: "0.4.0"`、`last_verified_at: "2026-11-26"`。

- [ ] **Step 2: 文档补充**

- `docs/templates/literature-sites/README.md`：在 pdf 字段说明处加 `interstitial` 五个子字段（`url_contains` 必填 / `host_fallbacks` / `tab_timeout_s` / `sleep_after_open_s` / `attempt_timeout_s`）与"何时使用"（入口先跳中间页再跳最终地址、最终地址主机可能错误）。
- `backend/literature/README.md` §3.4：追加一段"中间页下载"流程说明（与本文档 Architecture 段一致），并在限制节说明"浏览器标签页由 `browser_tabs create` 打开，工具可见；站点 `window.open` 弹窗不可见，不要依赖"。
- `docs/technical/164-...md` §2.5 字段表补 `pdf.interstitial`；§3.4 下载小节补新路径；§6 实测结论补 2026-11-26 的 oversea→kns 根因与验证数字（1,070,254B curl / 1,688,310B 浏览器）。

- [ ] **Step 3: 校验**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m backend.literature.cli validate-profile --path docs/templates/literature-sites/xueshu789.yaml
```

预期：`{"ok": true, "id": "xueshu789", "status": "ready"}`。

- [ ] **Step 4: Commit**

```bash
git add docs/templates/literature-sites/xueshu789.yaml docs/templates/literature-sites/README.md backend/literature/README.md docs/technical/164-literature-research-subsystem.md
git commit -m "docs(literature): xueshu789 模板与文档补中间页主机回退"
```

---

### Task 6: SKILL.md 下载步骤对齐

**Files:**
- Modify: `backend/skills/skill_md/shipped/literature-research/SKILL.md`

- [ ] **Step 1: 更新 §3 下载说明**

在「### 3. 检索」第 3 点后追加：

```markdown
   下载单篇（推荐用 helper，不要手点弹窗——站点 `window.open` 弹窗对工具不可见）：

   ```python
   from pathlib import Path
   from backend.literature.profile_store import get_default_store
   from backend.literature.search import download_pdf
   from backend.literature.sage_driver import SageToolDriver

   profile = get_default_store().get("xueshu789")
   res = download_pdf(
       profile, SageToolDriver(sage.call), expected_title="论文题名",
       dest_dir=Path("<run_dir>/pdf"),
       entry_selector="table.result-table-list tbody tr:nth-child(1) a.downloadlink",
   )
   print(res.ok, res.path, res.errors)
   ```

   - profile 声明 `pdf.interstitial` 时，helper 会：读取行内 `a.downloadlink` 完整
     href（含 `&ddata=`）→ 新标签打开 doDownload → 等中间页 2s 跳转 → 按
     `host_fallbacks` 先换 `kns.cnki.net` 再原域兜底 → 等下载并校验 `%PDF-` 与题名。
   - 无 interstitial 配置的站点仍走原「点击入口」路径（`download_pdf` 自动选择）。
   - 下载完成后中间页标签会被关闭；失败时把 `res.errors` 反馈给用户，不要反复重试。
```

- [ ] **Step 2: 语法自检**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_skill_md_loader.py -q
```

- [ ] **Step 3: Commit**

```bash
git add backend/skills/skill_md/shipped/literature-research/SKILL.md
git commit -m "docs(skill): literature-research 下载步骤改用 download_pdf 中间页路径"
```

---

### Task 7: 门禁与基线

**Files:**
- Modify: `architecture-baseline.json`（如 `browser_tool.py` 超基线）

- [ ] **Step 1: 跑相关测试集**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_pipeline.py \
  backend/tests/unit/test_literature_site_profiles.py \
  backend/tests/unit/test_browser_tool.py -q
```

- [ ] **Step 2: ruff + py38 兼容**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/literature backend/tools/browser_tool.py backend/tests/unit/test_literature_pipeline.py backend/tests/unit/test_literature_site_profiles.py backend/tests/unit/test_browser_tool.py
/home/fz/anaconda3/envs/sage-backend/bin/python scripts/check_py38_compat.py
```

- [ ] **Step 3: 架构棘轮**

```bash
node scripts/architecture-check.mjs 2>/dev/null || node --experimental-vm-modules scripts/architecture-check.mjs
```

若 `backend/tools/browser_tool.py` 超基线：按 CI 提示把 `architecture-baseline.json` 里该条目改为当前 `wc -l` 值（棘轮只升不降），提交：

```bash
git add architecture-baseline.json
git commit -m "chore(architecture): 更新 browser_tool.py 行数基线（interact attr 动作）"
```

- [ ] **Step 4: 全量文献 + 工具回归**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit -q -k "literature or browser"
```

预期：全部 PASS（记录数字）。

---

### Task 8: 真机端到端验证（合并后 / 用户重启桌面端时执行）

**依赖：** 需要后端加载本分支代码。当前运行中的桌面端来自主目录代码，无法热切换；合并后重启桌面端执行。

- [ ] **Step 1: 用户级模板同步（不进仓库）**

把 `docs/templates/literature-sites/xueshu789.yaml` 的 `pdf.interstitial` 段合并进 `~/.sage/literature_sites/xueshu789.yaml`（旧代码会忽略未知字段，可提前改）。

- [ ] **Step 2: 重启桌面端并登录**

```bash
cd /home/fz/project/sage && npm run dev
SAGE_PYTHON=/home/fz/anaconda3/envs/sage-backend/bin/python ./node_modules/.bin/electron --no-sandbox .
```

在「Sage 浏览器」窗口登录 xueshu789（卡号+密码，不代填）。

- [ ] **Step 3: 走真实链路**

用 agent 执行 literature-research 的检索 → 选 1 篇 → 按 SKILL.md 调 `download_pdf(entry_selector=第 N 行)`；确认：
- `res.ok == True`，`res.path` 指向 `%PDF-1.6` 文件、文件名含题名；
- 中间页标签已被关闭；浏览器下载目录出现新 PDF（如 1.7MB 级）。

- [ ] **Step 4: 记录结果**

把实测结果（文件大小/题名/run_id）追加到 `docs/technical/164-...md` 的实测小节或项目记忆。

---

## 风险评估

| 风险 | 缓解 |
| --- | --- |
| `browser_navigate` 到附件 URL 报 `net::ERR_ABORTED` | helper 捕获导航异常后继续 `wait_download`（Task 4 测试覆盖） |
| 嵌入会话下载事件通道不可用（tracker 未连接） | `browser_downloads` 已有目录列举回退；下载目录由 `_apply_download_behavior` 固定，落盘路径可枚举 |
| `attr` 动作被用于读取敏感属性 | 只读动作、不产生副作用；安全分类默认 ok；值截断 4000 字符；仍受站点策略与审计约束 |
| 多篇下载时行选择器写错 | 校验文件名与题名互相包含，失败即报错不误报成功 |
| 中间页时序变化（2s 跳转） | `sleep_after_open_s` + `tab_timeout_s` 均可在 profile 调整；识别基于 URL 子串而非固定时序 |
| 站点后续改回直接下载 | interstitial 路径在 `url_contains` 匹配不到标签时明确报错，不会误判成功；原点击路径保留 |
| 行数棘轮 | Task 7 同步更新 `architecture-baseline.json` |
