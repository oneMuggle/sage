// spec: docs/mcp-android-implementation-plan.md §6 — Room 与 JSON/核心层模型之间的映射，保留幂等性等全部语义
package ai.arena.companion.data.room

import ai.arena.companion.data.ArchiveEntry
import ai.arena.companion.data.TaskSettings
import ai.arena.companion.data.ModelRoundRecord
import ai.arena.companion.identity.ConversationIdentity
import org.json.JSONArray
import org.json.JSONObject

fun ArchiveEntryEntity.toModel(): ArchiveEntry {
    val history = try {
        val arr = JSONArray(modelHistoryJson)
        (0 until arr.length()).map { i ->
            val obj = arr.getJSONObject(i)
            ModelRoundRecord(
                round = obj.optInt("round", 1),
                model = obj.optString("model", ""),
                internal = obj.optString("internal").takeIf { it.isNotEmpty() },
                reasoning = if (obj.has("reasoning") && !obj.isNull("reasoning")) obj.getLong("reasoning") else null,
                timestamp = obj.optLong("timestamp", 0L)
            )
        }
    } catch (_: Exception) {
        emptyList()
    }
    return ArchiveEntry(
        id = id,
        title = title,
        model = model,
        url = url,
        profile = profile,
        email = email,
        prompt = prompt,
        collectedAt = collectedAt,
        modelFolder = modelFolder,
        shortcut = shortcut,
        renamed = renamed,
        renameError = renameError,
        exportedAt = exportedAt,
        exportedFolder = exportedFolder,
        accountId = accountId,
        creditsRemaining = creditsRemaining,
        modelHistory = history,
        modelDrifted = modelDrifted,
    )
}

fun ArchiveEntry.toEntity(instanceName: String): ArchiveEntryEntity {
    val canonical = ConversationIdentity.created(url)?.let {
        // 规范化后去格式相同的链接视为同一条，对应 ArchiveStore.same()
        try { java.net.URI(it).toString().lowercase() } catch (_: Exception) { it.lowercase() }
    } ?: url.lowercase()
    val histJson = try {
        val arr = JSONArray()
        modelHistory.forEach { rec ->
            val obj = JSONObject().apply {
                put("round", rec.round)
                put("model", rec.model)
                rec.internal?.let { put("internal", it) }
                rec.reasoning?.let { put("reasoning", it) }
                put("timestamp", rec.timestamp)
            }
            arr.put(obj)
        }
        arr.toString()
    } catch (_: Exception) {
        "[]"
    }
    return ArchiveEntryEntity(
        id = id,
        instanceName = instanceName,
        canonicalUrl = canonical,
        url = url,
        title = title,
        model = model,
        modelFolder = modelFolder,
        shortcut = shortcut,
        profile = profile,
        email = email,
        prompt = prompt,
        collectedAt = collectedAt,
        exportedAt = exportedAt,
        exportedFolder = exportedFolder,
        renamed = renamed,
        renameError = renameError,
        accountId = accountId,
        creditsRemaining = creditsRemaining,
        modelHistoryJson = histJson,
        modelDrifted = modelDrifted,
    )
}

fun TaskSettingsEntity.toModel(): TaskSettings {
    val models = try { JSONArray(excludedModelsJson).let { arr -> (0 until arr.length()).map { arr.getString(it) } } } catch (_: Exception) { emptyList() }
    return TaskSettings(
        prompt = prompt,
        excludedModels = models.toMutableList(),
        pauseOnCaptcha = pauseOnCaptcha,
        stepPauseSeconds = stepPauseSeconds,
        stepPauseJitterSeconds = stepPauseJitterSeconds,
        attachments = mutableListOf(),
    )
}

fun TaskSettings.toEntity(instanceName: String): TaskSettingsEntity {
    val arr = JSONArray().apply { excludedModels.forEach { put(it) } }
    return TaskSettingsEntity(
        instanceName = instanceName,
        prompt = prompt,
        excludedModelsJson = arr.toString(),
        pauseOnCaptcha = pauseOnCaptcha,
        stepPauseSeconds = stepPauseSeconds,
        stepPauseJitterSeconds = stepPauseJitterSeconds,
        attachmentsJson = "[]",
    )
}
