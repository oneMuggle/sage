// ref: ArchiveStore.cs / ArchiveEntry.cs
// spec: docs/mcp-android-implementation-plan.md §3.8 / §6（(instance, canonicalUrl) 唯一 → 幂等）
package ai.arena.companion.data.room

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query

@Entity(
    tableName = "archive_entries",
    indices = [Index(value = ["instanceName", "canonicalUrl"], unique = true)],
)
data class ArchiveEntryEntity(
    @PrimaryKey val id: String,
    val instanceName: String,
    val canonicalUrl: String,
    val url: String,
    val title: String? = null,
    val model: String? = null,
    val modelFolder: String? = null,
    val shortcut: String? = null,
    val profile: String? = null,
    val email: String? = null,
    val prompt: String? = null,
    val collectedAt: String? = null,
    val exportedAt: String? = null,
    val exportedFolder: String? = null,
    val renamed: Boolean = false,
    val renameError: String? = null,
    val accountId: String? = null,
    val creditsRemaining: Long? = null,
    val modelHistoryJson: String = "[]",
    val modelDrifted: Boolean = false,
)

@Dao
interface ArchiveEntryDao {
    @Query("SELECT * FROM archive_entries WHERE instanceName = :instance ORDER BY collectedAt DESC")
    suspend fun allForInstance(instance: String): List<ArchiveEntryEntity>

    @Query("SELECT * FROM archive_entries ORDER BY collectedAt DESC")
    suspend fun all(): List<ArchiveEntryEntity>

    @Query("SELECT * FROM archive_entries WHERE canonicalUrl = :canonical LIMIT 1")
    suspend fun findByCanonical(canonical: String): ArchiveEntryEntity?

    @Query("SELECT * FROM archive_entries WHERE id = :id LIMIT 1")
    suspend fun findById(id: String): ArchiveEntryEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entity: ArchiveEntryEntity)

    @Query("DELETE FROM archive_entries WHERE id = :id")
    suspend fun deleteById(id: String): Int

    @Query("DELETE FROM archive_entries WHERE id IN (:ids)")
    suspend fun deleteMany(ids: List<String>): Int

    @Query("SELECT * FROM archive_entries WHERE instanceName = :instance AND modelFolder = :folder ORDER BY collectedAt ASC")
    suspend fun byModelFolder(instance: String, folder: String): List<ArchiveEntryEntity>

    @Query("SELECT * FROM archive_entries WHERE model = :model ORDER BY collectedAt DESC")
    suspend fun byModel(model: String): List<ArchiveEntryEntity>

    @Query("SELECT * FROM archive_entries WHERE email = :email ORDER BY collectedAt DESC")
    suspend fun byEmail(email: String): List<ArchiveEntryEntity>
}
