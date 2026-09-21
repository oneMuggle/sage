// spec: docs/mcp-android-implementation-plan.md §6 Room schema（取代 JSON 文件树）
package ai.arena.companion.data.room

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverters

@Database(
    entities = [
        InstanceEntity::class,
        ArchiveEntryEntity::class,
        TaskSettingsEntity::class,
        AttachmentEntity::class,
        RateLimitEntity::class,
        JobStateEntity::class,
        AccountEntity::class,
    ],
    version = 1,
    exportSchema = false,
)
@TypeConverters(Converters::class)
abstract class ArenaDatabase : RoomDatabase() {
    abstract fun instanceDao(): InstanceDao
    abstract fun archiveEntryDao(): ArchiveEntryDao
    abstract fun taskSettingsDao(): TaskSettingsDao
    abstract fun attachmentDao(): AttachmentDao
    abstract fun rateLimitDao(): RateLimitDao
    abstract fun jobStateDao(): JobStateDao
    abstract fun accountDao(): AccountDao

    companion object {
        @Volatile private var INSTANCE: ArenaDatabase? = null

        fun get(context: Context): ArenaDatabase =
            INSTANCE ?: synchronized(this) {
                INSTANCE ?: Room.databaseBuilder(
                    context.applicationContext,
                    ArenaDatabase::class.java,
                    "arena-companion.db",
                )
                    .fallbackToDestructiveMigrationOnDowngrade()
                    .build().also { INSTANCE = it }
            }

        fun inMemory(context: Context): ArenaDatabase =
            Room.inMemoryDatabaseBuilder(context, ArenaDatabase::class.java)
                .allowMainThreadQueries()
                .build()
    }
}
