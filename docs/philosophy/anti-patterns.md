# 反模式详解

> 本文档详细列出 Sage 项目中必须避免的反模式，每个反模式都包含具体示例和正确做法。

---

## 什么是反模式？

**反模式（Anti-pattern）** 是指看似合理但实际上会导致问题的做法。在 Sage 项目中，我们明确定义了 4 类必须避免的反模式。

---

## 反模式 1：黑盒决策 ❌

### 定义

**系统在不解释的情况下做出决策。**

### 为什么有害

- 用户无法理解系统行为
- 难以调试和排查问题
- 降低用户信任度
- 无法审计决策过程

### 具体示例

#### ❌ 错误做法

```python
# 示例 1：黑盒推荐
def recommend_content(user_id: str) -> List[Content]:
    """推荐内容（黑盒）"""
    # 不知道推荐逻辑是什么
    return recommendation_engine.get_recommendations(user_id)

# 示例 2：黑盒过滤
def should_block_user(user_action: str) -> bool:
    """判断是否封禁用户（黑盒）"""
    # 不知道为什么封禁
    return risk_analyzer.analyze(user_action) > 0.8

# 示例 3：黑盒排序
def sort_results(results: List[Result]) -> List[Result]:
    """排序结果（黑盒）"""
    # 不知道排序依据
    return sorted(results, key=ranking_function)
```

#### ✅ 正确做法

```python
# 示例 1：可解释的推荐
def recommend_content(user_id: str) -> RecommendationResult:
    """推荐内容（可解释）"""
    user_profile = get_user_profile(user_id)
    reasons = []
    
    # 基于兴趣推荐
    if user_profile.interests:
        content = find_content_by_interests(user_profile.interests)
        reasons.append(f"基于您的兴趣: {', '.join(user_profile.interests)}")
    
    # 基于历史推荐
    history = get_user_history(user_id)
    similar_content = find_similar_content(history)
    reasons.append(f"与您过去喜欢的内容相似")
    
    return RecommendationResult(
        recommendations=content + similar_content,
        reasons=reasons,
        confidence=0.85
    )

# 示例 2：可解释的风控
def should_block_user(user_action: str) -> RiskAssessment:
    """判断是否封禁用户（可解释）"""
    risks = []
    
    # 检查敏感操作
    if contains_sensitive_operation(user_action):
        risks.append(Risk(
            type="sensitive_operation",
            severity=0.9,
            reason="包含敏感操作（如删除所有数据）"
        ))
    
    # 检查异常行为
    if is_abnormal_pattern(user_action):
        risks.append(Risk(
            type="abnormal_pattern",
            severity=0.7,
            reason="行为模式异常（短时间内大量请求）"
        ))
    
    total_risk = sum(r.severity for r in risks)
    
    return RiskAssessment(
        should_block=total_risk > 0.8,
        risks=risks,
        total_risk=total_risk,
        recommendation="建议封禁" if total_risk > 0.8 else "建议观察"
    )

# 示例 3：可解释的排序
def sort_results(results: List[Result], query: str) -> SortedResults:
    """排序结果（可解释）"""
    scored_results = []
    
    for result in results:
        score = 0
        reasons = []
        
        # 相关性评分
        relevance = calculate_relevance(result, query)
        score += relevance * 0.5
        reasons.append(f"相关性: {relevance:.2f}")
        
        # 新鲜度评分
        freshness = calculate_freshness(result)
        score += freshness * 0.3
        reasons.append(f"新鲜度: {freshness:.2f}")
        
        # 权威度评分
        authority = calculate_authority(result)
        score += authority * 0.2
        reasons.append(f"权威度: {authority:.2f}")
        
        scored_results.append(ScoredResult(
            result=result,
            score=score,
            reasons=reasons
        ))
    
    sorted_results = sorted(scored_results, key=lambda x: x.score, reverse=True)
    
    return SortedResults(
        results=sorted_results,
        ranking_explanation="按相关性(50%) + 新鲜度(30%) + 权威度(20%)排序"
    )
```

### 检查清单

- [ ] 每个决策是否都有明确的理由
- [ ] 用户能否理解决策过程
- [ ] 是否有决策日志
- [ ] 是否能解释为什么这样做

---

## 反模式 2：不可逆操作 ❌

### 定义

**无法撤销的操作。**

### 为什么有害

- 用户无法挽回错误
- 增加用户焦虑感
- 降低用户信任度
- 可能导致数据丢失

### 具体示例

#### ❌ 错误做法

```python
# 示例 1：永久删除
def delete_memory(memory_id: str):
    """删除记忆（永久）"""
    db.execute(f"DELETE FROM memories WHERE id = '{memory_id}'")
    # 无法恢复

# 示例 2：覆盖更新
def update_config(key: str, value: str):
    """更新配置（覆盖）"""
    config[key] = value
    # 旧值丢失

# 示例 3：批量操作
def batch_delete(memory_ids: List[str]):
    """批量删除（无备份）"""
    for id in memory_ids:
        db.execute(f"DELETE FROM memories WHERE id = '{id}'")
    # 无法回滚
```

#### ✅ 正确做法

```python
# 示例 1：软删除
def delete_memory(memory_id: str) -> DeletionReceipt:
    """删除记忆（软删除，可恢复）"""
    memory = db.find(memory_id)
    
    # 标记为已删除
    memory.status = "deleted"
    memory.deleted_at = datetime.utcnow()
    memory.deleted_by = get_current_user()
    
    db.update(memory)
    
    # 返回删除凭证
    return DeletionReceipt(
        memory_id=memory_id,
        deleted_at=memory.deleted_at,
        recovery_deadline=memory.deleted_at + timedelta(days=30),
        recovery_instructions="在 30 天内可从回收站恢复"
    )

# 示例 2：版本化更新
def update_config(key: str, value: str) -> ConfigVersion:
    """更新配置（版本化，可回滚）"""
    old_value = config.get(key)
    
    # 保存历史版本
    version = ConfigVersion(
        key=key,
        old_value=old_value,
        new_value=value,
        updated_at=datetime.utcnow(),
        updated_by=get_current_user()
    )
    db.insert("config_versions", version)
    
    # 更新当前值
    config[key] = value
    
    return version

def rollback_config(key: str, version_id: str):
    """回滚配置到指定版本"""
    version = db.find("config_versions", version_id)
    config[key] = version.old_value
    log.info(f"Rolled back config {key} to version {version_id}")

# 示例 3：带备份的批量操作
def batch_delete(memory_ids: List[str]) -> BatchOperationReceipt:
    """批量删除（带备份，可回滚）"""
    # 创建备份
    backup_id = str(uuid.uuid4())
    backup_data = []
    
    for id in memory_ids:
        memory = db.find(id)
        backup_data.append(memory)
    
    db.insert("backups", {
        "id": backup_id,
        "data": backup_data,
        "created_at": datetime.utcnow()
    })
    
    # 执行删除
    for id in memory_ids:
        db.execute(f"DELETE FROM memories WHERE id = '{id}'")
    
    # 返回操作凭证
    return BatchOperationReceipt(
        backup_id=backup_id,
        deleted_count=len(memory_ids),
        recovery_deadline=datetime.utcnow() + timedelta(days=30),
        recovery_instructions=f"使用 backup_id={backup_id} 可恢复"
    )

def restore_backup(backup_id: str):
    """从备份恢复"""
    backup = db.find("backups", backup_id)
    for memory in backup.data:
        db.insert("memories", memory)
    log.info(f"Restored backup {backup_id}")
```

### 检查清单

- [ ] 删除操作是否可恢复（软删除）
- [ ] 更新操作是否保留历史版本
- [ ] 批量操作是否有备份
- [ ] 是否提供回滚机制
- [ ] 用户是否知道如何恢复

---

## 反模式 3：静默失败 ❌

### 定义

**错误被无声吞没，用户不知情。**

### 为什么有害

- 问题难以发现和排查
- 用户不知道发生了什么
- 可能导致更严重的问题
- 降低系统可靠性

### 具体示例

#### ❌ 错误做法

```python
# 示例 1：吞掉异常
def process_data(data: dict):
    """处理数据（吞掉异常）"""
    try:
        result = complex_processing(data)
        return result
    except Exception:
        pass  # 吞掉所有异常

# 示例 2：忽略错误码
def call_api(endpoint: str) -> dict:
    """调用 API（忽略错误）"""
    response = requests.post(endpoint, json={})
    # 不检查 response.status_code
    return response.json()

# 示例 3：静默降级
def get_recommendations(user_id: str) -> List[Content]:
    """获取推荐（静默降级）"""
    try:
        return recommendation_service.get(user_id)
    except:
        return []  # 失败时返回空列表，用户不知情
```

#### ✅ 正确做法

```python
# 示例 1：显式错误处理
def process_data(data: dict) -> ProcessingResult:
    """处理数据（显式错误处理）"""
    try:
        result = complex_processing(data)
        return ProcessingResult(success=True, data=result)
    except ValueError as e:
        log.error(f"Invalid data: {e}")
        return ProcessingResult(
            success=False,
            error=f"数据格式错误: {e}",
            suggestion="请检查数据格式"
        )
    except Exception as e:
        log.error(f"Processing failed: {e}")
        return ProcessingResult(
            success=False,
            error=f"处理失败: {e}",
            suggestion="请稍后重试"
        )

# 示例 2：检查错误码
def call_api(endpoint: str) -> APIResponse:
    """调用 API（检查错误）"""
    response = requests.post(endpoint, json={})
    
    if response.status_code >= 400:
        error_msg = response.json().get("error", "Unknown error")
        log.error(f"API call failed: {response.status_code} - {error_msg}")
        raise APIError(
            status_code=response.status_code,
            message=error_msg,
            suggestion="请检查请求参数" if response.status_code == 400 else "请稍后重试"
        )
    
    return APIResponse(
        success=True,
        data=response.json()
    )

# 示例 3：显式降级
def get_recommendations(user_id: str) -> RecommendationResult:
    """获取推荐（显式降级）"""
    try:
        recommendations = recommendation_service.get(user_id)
        return RecommendationResult(
            success=True,
            data=recommendations,
            source="recommendation_service"
        )
    except Exception as e:
        log.warning(f"Recommendation service failed: {e}, using fallback")
        
        # 使用降级方案
        fallback = get_popular_content()
        
        return RecommendationResult(
            success=True,
            data=fallback,
            source="fallback",
            notice="推荐服务暂时不可用，显示热门内容"
        )
```

### 检查清单

- [ ] 是否有 try-except 捕获异常
- [ ] 异常是否被记录到日志
- [ ] 用户是否收到错误提示
- [ ] 是否提供恢复建议
- [ ] 降级时是否通知用户

---

## 反模式 4：数据锁定 ❌

### 定义

**用户无法访问自己的数据。**

### 为什么有害

- 违反用户权利（数据可携带权）
- 降低用户信任度
- 可能违反法规（如 GDPR）
- 用户被"锁定"在系统中

### 具体示例

#### ❌ 错误做法

```python
# 示例 1：专有格式
def save_data(data: dict):
    """保存数据（专有格式）"""
    with open("data.sage", "wb") as f:
        pickle.dump(data, f)  # 专有格式，无法迁移

# 示例 2：无法导出
class UserManager:
    def get_user(self, user_id: str) -> User:
        """获取用户（无法导出所有数据）"""
        return db.find(user_id)
    # 没有 export_all 方法

# 示例 3：无法删除
class DataManager:
    def save(self, data: dict):
        """保存数据（无法删除）"""
        db.insert(data)
    # 没有 delete 方法
```

#### ✅ 正确做法

```python
# 示例 1：标准格式
def save_data(data: dict):
    """保存数据（标准 JSON 格式）"""
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def export_to_standard_formats(data: dict, format: str) -> bytes:
    """导出为标准格式"""
    if format == "json":
        return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    elif format == "csv":
        return dict_to_csv(data)
    elif format == "xml":
        return dict_to_xml(data)
    else:
        raise ValueError(f"Unsupported format: {format}")

# 示例 2：完整的数据导出
class UserManager:
    def get_user(self, user_id: str) -> User:
        """获取用户"""
        return db.find(user_id)
    
    def export_all_data(self, user_id: str) -> ExportResult:
        """导出用户所有数据"""
        user = self.get_user(user_id)
        
        export_data = {
            "profile": {
                "name": user.name,
                "email": user.email,
                "created_at": user.created_at.isoformat(),
            },
            "memories": [
                {
                    "id": m.id,
                    "content": m.content,
                    "created_at": m.created_at.isoformat(),
                }
                for m in db.find_memories(user_id)
            ],
            "conversations": [
                {
                    "id": c.id,
                    "messages": c.messages,
                    "created_at": c.created_at.isoformat(),
                }
                for c in db.find_conversations(user_id)
            ],
            "preferences": db.find_preferences(user_id),
        }
        
        return ExportResult(
            format="json",
            data=export_data,
            exported_at=datetime.utcnow().isoformat(),
            size=len(json.dumps(export_data))
        )
    
    def download_export(self, user_id: str, format: str = "json") -> bytes:
        """下载导出数据"""
        export = self.export_all_data(user_id)
        return export_to_standard_formats(export.data, format)

# 示例 3：完整的数据删除
class DataManager:
    def save(self, data: dict):
        """保存数据"""
        db.insert(data)
    
    def delete(self, data_id: str) -> DeletionReceipt:
        """删除数据"""
        data = db.find(data_id)
        
        # 软删除
        data.status = "deleted"
        data.deleted_at = datetime.utcnow()
        db.update(data)
        
        return DeletionReceipt(
            data_id=data_id,
            deleted_at=data.deleted_at,
            recovery_deadline=data.deleted_at + timedelta(days=30)
        )
    
    def delete_all_user_data(self, user_id: str) -> DeletionReceipt:
        """删除用户所有数据"""
        # 删除记忆
        for memory in db.find_memories(user_id):
            self.delete(memory.id)
        
        # 删除对话
        for conversation in db.find_conversations(user_id):
            self.delete(conversation.id)
        
        # 删除偏好
        db.delete_preferences(user_id)
        
        return DeletionReceipt(
            user_id=user_id,
            deleted_count=db.count_deleted(user_id),
            deleted_at=datetime.utcnow()
        )
```

### 检查清单

- [ ] 数据是否使用标准格式（JSON/CSV/XML）
- [ ] 用户能否导出所有数据
- [ ] 用户能否删除特定数据
- [ ] 用户能否删除所有数据
- [ ] 导出数据是否完整（包括元数据）
- [ ] 是否提供数据迁移指南

---

## 总结

| 反模式 | 危害 | 正确做法 |
|--------|------|----------|
| 黑盒决策 | 用户无法理解 | 提供可解释的决策 |
| 不可逆操作 | 用户无法挽回 | 提供回滚机制 |
| 静默失败 | 问题难以发现 | 显式错误处理 |
| 数据锁定 | 用户被锁定 | 支持导出和删除 |

**记住**：避免反模式不是可选的，而是必须的。每个 PR 都应该检查是否引入了反模式。
