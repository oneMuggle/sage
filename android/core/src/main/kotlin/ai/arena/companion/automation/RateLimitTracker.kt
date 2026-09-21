// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/RateLimitTracker.cs
// spec: docs/mcp-android-implementation-plan.md §3.5
package ai.arena.companion.automation

import java.net.URI
import java.time.Instant
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

data class RateLimitRecord(
    val sequence: Int = 0,
    val requestUrl: String? = null,
    val retryUntilUtc: String? = null,
)

/** 记录持久化的抽象；Android 侧由 Room/文件实现，核心层保持可测。 */
interface RateLimitStore {
    fun load(): RateLimitRecord?
    /** 实现必须原子写入（tmp + replace）。 */
    fun save(record: RateLimitRecord)
}

/**
 * 只对 https://arena.ai/nextjs-api/stream/create-chat 的 429 生效。
 * 跨页面槽共享的只有 deadline，绝不共享 response id——
 * 一个槽的 429 绝不能被误认为另一个槽的失败提交。
 */
class RateLimitTracker(private val scopeKey: String, private val store: RateLimitStore) {

    private var record: RateLimitRecord = RateLimitRecord()

    init {
        try {
            val loaded = store.load()
            if (loaded != null && matches(loaded.requestUrl)) {
                record = loaded
                parseInstant(loaded.retryUntilUtc)?.let { shareDeadline(it) }
            }
        } catch (_: Exception) {
            // 与 C# 版一致：IO/参数异常吞掉，按无记录处理。
        }
    }

    private fun shareDeadline(until: Instant) {
        synchronized(deadlineLock) {
            val previous = sharedDeadlines[scopeKey]
            if (previous == null || until.isAfter(previous)) sharedDeadlines[scopeKey] = until
        }
    }

    fun observe(url: String?, status: Int, header: String?, serverDate: String?, now: Instant) {
        if (status != 429 || !matches(url)) return
        var deadline = parse(header, serverDate, now)
        deadline?.let { shareDeadline(it) }
        synchronized(deadlineLock) {
            val shared = sharedDeadlines[scopeKey]
            if (shared != null && shared.isAfter(now) && (deadline == null || shared.isAfter(deadline))) {
                deadline = shared
            }
        }
        record = RateLimitRecord(
            sequence = record.sequence + 1,
            requestUrl = url,
            retryUntilUtc = deadline?.let { ISO.format(it.atZone(java.time.ZoneOffset.UTC)) },
        )
        store.save(record)
    }

    fun apply(state: PageState) {
        state.rateLimitId = record.sequence
        state.rateLimitRetryAt = parseInstant(record.retryUntilUtc) ?: Instant.MIN
        synchronized(deadlineLock) {
            val shared = sharedDeadlines[scopeKey]
            if (shared != null && shared.isAfter(state.rateLimitRetryAt)) state.rateLimitRetryAt = shared
        }
    }

    companion object {
        private val deadlineLock = Any()
        private val sharedDeadlines = HashMap<String, Instant>()
        private val ISO: DateTimeFormatter = DateTimeFormatter.ISO_OFFSET_DATE_TIME

        /** 测试隔离用。 */
        fun resetSharedDeadlines() {
            synchronized(deadlineLock) { sharedDeadlines.clear() }
        }

        fun matches(url: String?): Boolean {
            if (url.isNullOrBlank()) return false
            val u = try { URI(url) } catch (_: Exception) { return false }
            if (!u.isAbsolute || u.scheme != "https" || u.host != "arena.ai") return false
            return u.rawPath == "/nextjs-api/stream/create-chat"
        }

        /** 纯数字秒钳到 [1, Int.MAX]；HTTP-date 优先用与 server Date 的差值。 */
        fun parse(header: String?, serverDate: String?, now: Instant): Instant? {
            val h = (header ?: "").trim()
            if (h.isEmpty()) return null
            h.toLongOrNull()?.let { seconds ->
                if (seconds < 0 || seconds > Int.MAX_VALUE) return null
                return now.plusSeconds(maxOf(1L, seconds))
            }
            val target = parseHttpDate(h) ?: return null
            val server = parseHttpDate(serverDate)
            if (server != null) {
                val delta = target.epochSecond - server.epochSecond
                return now.plusSeconds(maxOf(1L, delta))
            }
            return if (target.isAfter(now)) target else now.plusSeconds(1)
        }

        private fun parseHttpDate(value: String?): Instant? {
            if (value.isNullOrBlank()) return null
            for (fmt in listOf(DateTimeFormatter.RFC_1123_DATE_TIME, DateTimeFormatter.ISO_OFFSET_DATE_TIME)) {
                try {
                    return ZonedDateTime.parse(value.trim(), fmt).toInstant()
                } catch (_: Exception) {
                }
            }
            return null
        }

        private fun parseInstant(value: String?): Instant? {
            if (value.isNullOrBlank()) return null
            return try { ZonedDateTime.parse(value, ISO).toInstant() } catch (_: Exception) { null }
        }
    }
}
