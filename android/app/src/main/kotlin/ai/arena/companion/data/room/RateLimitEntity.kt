// ref: RateLimitTracker.cs
// spec: docs/mcp-android-implementation-plan.md §3.5 / §6（per-instance 持久 deadline）
package ai.arena.companion.data.room

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query

@Entity(tableName = "rate_limit")
data class RateLimitEntity(
    @PrimaryKey val instanceName: String,
    val deadlineUtc: String? = null,
    val retryCount: Int = 0,
)

@Dao
interface RateLimitDao {
    @Query("SELECT * FROM rate_limit WHERE instanceName = :instance LIMIT 1")
    suspend fun find(instance: String): RateLimitEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entity: RateLimitEntity)

    @Query("DELETE FROM rate_limit WHERE instanceName = :instance")
    suspend fun clear(instance: String): Int
}
