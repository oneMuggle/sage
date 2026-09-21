// ref: JobState.kt（安卓新增，修 R2）
// spec: docs/mcp-android-implementation-plan.md §7 第 3/4 条 / §6（新增 job_state 表）
package ai.arena.companion.data.room

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query

@Entity(tableName = "job_state")
data class JobStateEntity(
    @PrimaryKey val instanceName: String,
    val schemaVersion: Int = 1,
    val prompt: String,
    val limit: Int,
    val rounds: Int,
    val attempt: Int,
    val phase: String,
    val trackedUrl: String? = null,
    val lastModel: String? = null,
    val rateLimitRetries: Int = 0,
    val retryUntilUtc: String? = null,
    val websiteArchivedRounds: Int = 0,
    val savedAtUtc: String,
    val cleanShutdown: Boolean = false,
    val message: String? = null,
)

@Dao
interface JobStateDao {
    @Query("SELECT * FROM job_state WHERE instanceName = :instance LIMIT 1")
    suspend fun find(instance: String): JobStateEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entity: JobStateEntity)

    @Query("DELETE FROM job_state WHERE instanceName = :instance")
    suspend fun clear(instance: String): Int

    @Query("DELETE FROM job_state")
    suspend fun clearAll(): Int
}
