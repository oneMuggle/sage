// ref: AccountVault.kt / AccountData.cs（含换号流程字段）
// spec: docs/mcp-android-implementation-plan.md §5 / §6
package ai.arena.companion.data.room

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query

@Entity(tableName = "accounts")
data class AccountEntity(
    @PrimaryKey val instanceName: String,
    val email: String = "",
    val passwordCiphertext: String = "",
    val name: String = "",
    val verified: Boolean = false,
    val mailboxBeforeRefresh: String = "",
    val mailboxRefreshRequested: Boolean = false,
    val mailboxChangeConfirmed: Boolean = false,
    val excludedEmailsJson: String = "[]",
    val updatedAtUtc: String = "",
)

@Dao
interface AccountDao {
    @Query("SELECT * FROM accounts WHERE instanceName = :instance LIMIT 1")
    suspend fun find(instance: String): AccountEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entity: AccountEntity)

    @Query("DELETE FROM accounts WHERE instanceName = :instance")
    suspend fun delete(instance: String): Int
}
