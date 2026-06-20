# 贡献指南

> 感谢您考虑为 Sage 做出贡献！本文档将指导您如何参与项目开发。

---

## 行为准则

参与 Sage 项目即表示您同意遵守以下原则：

- **尊重**：尊重所有贡献者，无论经验水平
- **包容**：欢迎不同观点和背景
- **建设性**：提供建设性反馈，避免人身攻击
- **专业**：保持专业态度，专注于项目目标

---

## 设计哲学

在贡献代码之前，请务必阅读并理解 [PHILOSOPHY.md](./PHILOSOPHY.md)。

Sage 遵循 4 个核心设计原则：

1. **记忆优先** - 所有交互默认持久化，除非显式拒绝
2. **渐进式自演化** - Agent 可从错误中学习，但需人类审批
3. **透明可控** - 所有自动化行为可审计、可回滚
4. **简单胜于复杂** - 优先选择简单方案，除非复杂性能证明其价值

**每个 PR 都应该符合这些原则。**

### 检查清单

在提交 PR 前，请确认：

- [ ] 代码符合设计哲学
- [ ] 没有引入反模式（详见 [anti-patterns.md](./docs/philosophy/anti-patterns.md)）
- [ ] 决策过程透明（如有重大决策，使用 [决策框架](./docs/philosophy/decision-framework.md)）
- [ ] 代码简单易懂（新开发者能在 30 分钟内理解）

---

## 如何贡献

### 1. 报告 Bug

使用 GitHub Issues 报告 Bug，请包含：

- **清晰的标题**：简明扼要描述问题
- **复现步骤**：详细的操作步骤
- **期望行为**：你认为应该发生什么
- **实际行为**：实际发生了什么
- **环境信息**：操作系统、Sage 版本、依赖版本
- **截图/日志**：如果适用

### 2. 提出新功能

使用 GitHub Issues 提出新功能，请包含：

- **用户价值**：这个功能对用户有什么好处
- **使用场景**：用户会如何使用这个功能
- **实现思路**：如果有想法，可以分享

**注意**：新功能必须符合设计哲学，特别是"用户价值优先"和"简单优先"原则。

### 3. 提交代码

#### 3.1  fork 和克隆

```bash
# Fork 仓库（在 GitHub 上点击 Fork 按钮）

# 克隆到本地
git clone https://github.com/YOUR_USERNAME/sage.git
cd sage

# 添加上游仓库
git remote add upstream https://github.com/ORIGINAL_OWNER/sage.git
```

#### 3.2 创建分支

```bash
# 同步最新代码
git checkout main
git pull upstream main

# 创建功能分支
git checkout -b feat/your-feature-name

# 或创建修复分支
git checkout -b fix/your-bug-fix
```

**分支命名规范**：
- `feat/xxx` - 新功能
- `fix/xxx` - Bug 修复
- `docs/xxx` - 文档更新
- `refactor/xxx` - 代码重构
- `test/xxx` - 测试相关

#### 3.3 开发

```bash
# 安装依赖
npm install
cd backend && pip install -r requirements.txt && cd ..

# 启动开发环境
npm run dev  # 前端
cd backend && python main.py  # 后端
```

**编码规范**：
- 前端：遵循 ESLint 配置
- 后端：遵循 PEP 8（使用 Black 格式化）
- 提交信息：遵循 Conventional Commits

#### 3.4 测试

```bash
# 前端测试
npm run test

# 后端测试
cd backend && pytest
```

**测试要求**：
- 新功能必须有测试
- 测试覆盖率不低于 80%
- 所有测试必须通过

#### 3.5 提交

```bash
# 添加变更
git add .

# 提交（遵循 Conventional Commits）
git commit -m "feat: add memory export feature"

# 推送到你的 fork
git push origin feat/your-feature-name
```

**提交信息格式**：
```
<type>: <description>

[optional body]

[optional footer]
```

**类型**：
- `feat` - 新功能
- `fix` - Bug 修复
- `docs` - 文档更新
- `style` - 代码格式（不影响代码运行）
- `refactor` - 代码重构
- `test` - 测试相关
- `chore` - 构建/工具变更

#### 3.6 创建 Pull Request

1. 在 GitHub 上导航到你的 fork
2. 点击 "Compare & pull request"
3. 填写 PR 描述：
   - **变更内容**：你做了什么
   - **变更原因**：为什么要做这个变更
   - **测试情况**：如何测试的
   - **截图**：如果是 UI 变更
4. 关联相关 Issue（如果有）
5. 提交 PR

### 4. 代码审查

所有 PR 都需要经过代码审查。审查者会检查：

- **功能正确性**：代码是否按预期工作
- **设计哲学**：是否符合 Sage 的设计原则
- **代码质量**：是否清晰、可维护、可测试
- **测试覆盖**：是否有足够的测试
- **文档**：是否更新了相关文档

**审查流程**：
1. 自动化检查（CI/CD）
2. 至少 1 个维护者审查
3. 所有讨论解决
4. 审查通过，合并 PR

---

## 开发环境设置

### 前端

```bash
# 安装 Node.js (>= 18.x)
# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 构建
npm run build
```

### 后端

```bash
# 安装 Python (>= 3.8)
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
cd backend
pip install -r requirements.txt

# 启动服务
python main.py
```

### 数据库

```bash
# 初始化数据库
cd backend
python -c "from database import init_db; init_db()"
```

---

## 代码风格

### 前端（TypeScript/React）

- 使用 TypeScript
- 遵循 ESLint 配置
- 组件使用函数式组件
- 使用 React Hooks 管理状态
- 文件命名：`kebab-case.tsx`

### 后端（Python）

- 遵循 PEP 8
- 使用 Black 格式化
- 使用类型提示
- 函数长度不超过 50 行
- 文件长度不超过 800 行
- 文件命名：`snake_case.py`

### 提交信息

遵循 [Conventional Commits](https://www.conventionalcommits.org/)：

```
feat: add memory export feature

This allows users to export all their memories to a JSON file.

Closes #123
```

---

## 测试指南

### 前端测试

使用 Vitest + React Testing Library：

```typescript
import { render, screen } from '@testing-library/react';
import { MemoryPanel } from './MemoryPanel';

test('renders memory list', () => {
  render(<MemoryPanel memories={[]} />);
  expect(screen.getByText('No memories')).toBeInTheDocument();
});
```

### 后端测试

使用 pytest：

```python
import pytest
from backend.memory import MemoryManager

@pytest.mark.asyncio
async def test_memory_store():
    manager = MemoryManager()
    memory = await manager.store("test content")
    assert memory.content == "test content"
```

---

## 文档贡献

文档同样重要！你可以帮助：

- 修正拼写/语法错误
- 改进文档结构
- 添加示例代码
- 翻译文档
- 编写教程

文档位于：
- `README.md` - 项目总览
- `docs/` - 详细设计文档
- `docs/philosophy/` - 设计哲学文档

---

## 社区

- **GitHub Issues** - 报告 Bug 和提出新功能
- **GitHub Discussions** - 讨论和问答
- **Discord** - 实时交流（链接待添加）

---

## 认可

所有贡献者都会出现在项目的 Contributors 页面。

感谢你的贡献！🎉

---

## 许可证

贡献的代码将遵循项目的 MIT 许可证。
