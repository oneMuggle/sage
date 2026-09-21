// ref: TaskSettings.cs Attachments/<hash>/<name> + 第十五批
// spec: docs/mcp-android-implementation-plan.md §3.6 / §6（sha256 主键，引用计数）
package ai.arena.companion.data.room

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query

@Entity(tableName = "attachments")
data class AttachmentEntity(
    @PrimaryKey val sha256: String,
    val instanceName: String,
    val name: String,
    val path: String,
    val bytes: Long,
)

@Dao
interface AttachmentDao {
    @Query("SELECT * FROM attachments WHERE instanceName = :instance")
    suspend fun allForInstance(instance: String): List<AttachmentEntity>

    @Query("SELECT * FROM attachments WHERE sha256 = :hash LIMIT 1")
    suspend fun find(hash: String): AttachmentEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entity: AttachmentEntity)

    @Query("DELETE FROM attachments WHERE sha256 = :hash")
    suspend fun delete(hash: String): Int

    @Query("SELECT COUNT(*) FROM attachments WHERE sha256 = :hash")
    suspend fun countByHash(hash: String): Int
}
