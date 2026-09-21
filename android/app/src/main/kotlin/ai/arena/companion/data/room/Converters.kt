// spec: docs/mcp-android-implementation-plan.md §6 数据模型（Room 取代 JSON，保留全部语义）
package ai.arena.companion.data.room

import androidx.room.TypeConverter

class Converters {
    @TypeConverter
    fun fromStringList(value: List<String>?): String =
        value?.joinToString("\u001F") ?: ""

    @TypeConverter
    fun toStringList(value: String): List<String> =
        if (value.isEmpty()) emptyList() else value.split("\u001F")
}
