// ref: InstanceManager.cs — 实例名校验正则共享，Room 为持久形态
// spec: docs/mcp-android-implementation-plan.md §3.7 / §6
package ai.arena.companion.data.room

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query

@Entity(tableName = "instances")
data class InstanceEntity(
    @PrimaryKey val name: String,
    val createdAtUtc: String,
)

@Dao
interface InstanceDao {
    @Query("SELECT * FROM instances ORDER BY name COLLATE NOCASE ASC")
    suspend fun all(): List<InstanceEntity>

    @Query("SELECT * FROM instances WHERE name = :name LIMIT 1")
    suspend fun find(name: String): InstanceEntity?

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insert(entity: InstanceEntity)

    @Query("DELETE FROM instances WHERE name = :name")
    suspend fun delete(name: String): Int

    @Query("UPDATE instances SET name = :newName WHERE name = :oldName")
    suspend fun rename(oldName: String, newName: String): Int
}
