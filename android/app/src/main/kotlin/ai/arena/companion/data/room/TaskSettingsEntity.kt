// ref: TaskSettings.cs
// spec: docs/mcp-android-implementation-plan.md §3.6 / §6
package ai.arena.companion.data.room

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query

@Entity(tableName = "task_settings")
data class TaskSettingsEntity(
    @PrimaryKey val instanceName: String,
    val prompt: String = "1+1=",
    val excludedModelsJson: String = "[]",
    val pauseOnCaptcha: Boolean = true,
    val stepPauseSeconds: Double = 3.0,
    val stepPauseJitterSeconds: Double = 2.0,
    val attachmentsJson: String = "[]",
)

@Dao
interface TaskSettingsDao {
    @Query("SELECT * FROM task_settings WHERE instanceName = :instance LIMIT 1")
    suspend fun find(instance: String): TaskSettingsEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entity: TaskSettingsEntity)

    @Query("DELETE FROM task_settings WHERE instanceName = :instance")
    suspend fun delete(instance: String): Int
}
