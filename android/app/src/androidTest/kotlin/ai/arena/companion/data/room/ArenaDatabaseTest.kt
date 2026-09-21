// spec: docs/mcp-android-implementation-plan.md §6 Room schema（实体、DAO、(instance, canonicalUrl) 唯一幂等约束）
package ai.arena.companion.data.room

import ai.arena.companion.data.TaskSettings
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ArenaDatabaseTest {

    private lateinit var db: ArenaDatabase
    private lateinit var instanceDao: InstanceDao
    private lateinit var archiveDao: ArchiveEntryDao
    private lateinit var taskSettingsDao: TaskSettingsDao
    private lateinit var rateLimitDao: RateLimitDao
    private lateinit var jobStateDao: JobStateDao
    private lateinit var accountDao: AccountDao
    private lateinit var attachmentDao: AttachmentDao

    @Before
    fun setUp() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        db = Room.inMemoryDatabaseBuilder(context, ArenaDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        instanceDao = db.instanceDao()
        archiveDao = db.archiveEntryDao()
        taskSettingsDao = db.taskSettingsDao()
        rateLimitDao = db.rateLimitDao()
        jobStateDao = db.jobStateDao()
        accountDao = db.accountDao()
        attachmentDao = db.attachmentDao()
    }

    @After
    fun tearDown() {
        db.close()
    }

    @Test
    fun testInstanceDaoCrud() = runBlocking {
        val inst = InstanceEntity(name = "inst-alpha", createdAtUtc = "2026-09-20T10:00:00Z")
        instanceDao.insert(inst)

        val retrieved = instanceDao.find("inst-alpha")
        assertNotNull(retrieved)
        assertEquals("inst-alpha", retrieved?.name)
        assertEquals("2026-09-20T10:00:00Z", retrieved?.createdAtUtc)

        val all = instanceDao.all()
        assertEquals(1, all.size)

        instanceDao.rename("inst-alpha", "inst-beta")
        assertNull(instanceDao.find("inst-alpha"))
        assertNotNull(instanceDao.find("inst-beta"))

        instanceDao.delete("inst-beta")
        assertNull(instanceDao.find("inst-beta"))
    }

    @Test
    fun testArchiveEntryIdempotencyByCanonicalUrl() = runBlocking {
        val canonical = "https://arena.ai/c/chat-100"
        val entry1 = ArchiveEntryEntity(
            id = "entry-1",
            instanceName = "default",
            canonicalUrl = canonical,
            url = "https://arena.ai/c/chat-100/",
            title = "First Title",
            model = "gpt-4o",
            modelFolder = "gpt-4o",
            collectedAt = "2026-09-20 10:00:00",
            renamed = false
        )
        archiveDao.upsert(entry1)

        val found1 = archiveDao.findByCanonical(canonical)
        assertNotNull(found1)
        assertEquals("entry-1", found1?.id)
        assertEquals("First Title", found1?.title)

        // 重复归档同一会话：(instanceName, canonicalUrl) 保持唯一并替换原有记录
        val entry2 = ArchiveEntryEntity(
            id = "entry-2",
            instanceName = "default",
            canonicalUrl = canonical,
            url = "https://arena.ai/c/chat-100/",
            title = "Updated Title",
            model = "gpt-4o",
            modelFolder = "gpt-4o",
            collectedAt = "2026-09-20 10:05:00",
            renamed = true
        )
        archiveDao.upsert(entry2)

        val all = archiveDao.allForInstance("default")
        assertEquals("同一 (instanceName, canonicalUrl) 重复归档应保持幂等，只有 1 条记录", 1, all.size)
        assertEquals("Updated Title", all[0].title)
        assertTrue(all[0].renamed)
    }

    @Test
    fun testArchiveEntryDeleteManyAndByModelFolder() = runBlocking {
        val canonical1 = "https://arena.ai/c/item-1"
        val canonical2 = "https://arena.ai/c/item-2"
        val canonical3 = "https://arena.ai/c/item-3"

        archiveDao.upsert(ArchiveEntryEntity("id-1", "inst-1", canonical1, canonical1, "T1", "claude-3-5", "claude-3-5", collectedAt = "2026-09-20 10:00:00"))
        archiveDao.upsert(ArchiveEntryEntity("id-2", "inst-1", canonical2, canonical2, "T2", "claude-3-5", "claude-3-5", collectedAt = "2026-09-20 10:01:00"))
        archiveDao.upsert(ArchiveEntryEntity("id-3", "inst-1", canonical3, canonical3, "T3", "gemini-1-5", "gemini-1-5", collectedAt = "2026-09-20 10:02:00"))

        val claudeList = archiveDao.byModelFolder("inst-1", "claude-3-5")
        assertEquals(2, claudeList.size)
        assertEquals("id-1", claudeList[0].id)
        assertEquals("id-2", claudeList[1].id)

        val deletedCount = archiveDao.deleteMany(listOf("id-1", "id-2"))
        assertEquals(2, deletedCount)

        val remaining = archiveDao.allForInstance("inst-1")
        assertEquals(1, remaining.size)
        assertEquals("id-3", remaining[0].id)
    }

    @Test
    fun testTaskSettingsDaoAndRoundtripMappers() = runBlocking {
        val original = TaskSettings(
            prompt = "1+1=",
            excludedModels = mutableListOf("gpt-4o", "claude-3-5-sonnet"),
            pauseOnCaptcha = true,
            stepPauseSeconds = 5.0,
            stepPauseJitterSeconds = 2.0
        )
        val entity = original.toEntity("default")
        taskSettingsDao.upsert(entity)

        val loadedEntity = taskSettingsDao.find("default")
        assertNotNull(loadedEntity)
        val mapped = loadedEntity!!.toModel()

        assertEquals(original.prompt, mapped.prompt)
        assertEquals(original.excludedModels, mapped.excludedModels)
        assertEquals(original.pauseOnCaptcha, mapped.pauseOnCaptcha)
        assertEquals(original.stepPauseSeconds, mapped.stepPauseSeconds, 0.001)
        assertEquals(original.stepPauseJitterSeconds, mapped.stepPauseJitterSeconds, 0.001)
    }

    @Test
    fun testRateLimitDaoIsolation() = runBlocking {
        rateLimitDao.upsert(RateLimitEntity("inst-1", deadlineUtc = "2026-09-20T12:00:00Z", retryCount = 1))
        rateLimitDao.upsert(RateLimitEntity("inst-2", deadlineUtc = null, retryCount = 0))

        val r1 = rateLimitDao.find("inst-1")
        val r2 = rateLimitDao.find("inst-2")

        assertNotNull(r1)
        assertNotNull(r2)
        assertEquals("2026-09-20T12:00:00Z", r1?.deadlineUtc)
        assertEquals(1, r1?.retryCount)
        assertNull(r2?.deadlineUtc)
        assertEquals(0, r2?.retryCount)
    }

    @Test
    fun testJobStateDaoPersistence() = runBlocking {
        val job = JobStateEntity(
            instanceName = "default",
            prompt = "1+1=",
            limit = 10,
            rounds = 2,
            attempt = 1,
            phase = "observe",
            trackedUrl = "https://arena.ai/c/xyz",
            lastModel = "gpt-4o",
            savedAtUtc = "2026-09-20T12:00:00Z",
            cleanShutdown = false,
            message = "testing persistence"
        )
        jobStateDao.upsert(job)

        val loaded = jobStateDao.find("default")
        assertNotNull(loaded)
        assertEquals("observe", loaded?.phase)
        assertEquals(10, loaded?.limit)
        assertEquals(2, loaded?.rounds)
        assertEquals("https://arena.ai/c/xyz", loaded?.trackedUrl)
        assertEquals("gpt-4o", loaded?.lastModel)
        assertEquals("testing persistence", loaded?.message)
    }

    @Test
    fun testAccountDaoAndAttachmentDao() = runBlocking {
        accountDao.upsert(AccountEntity(
            instanceName = "default",
            email = "user@example.com",
            name = "tester",
            passwordCiphertext = "enc_aes_gcm_payload",
            verified = true,
            mailboxBeforeRefresh = "",
            updatedAtUtc = "2026-09-20T12:00:00Z"
        ))

        val account = accountDao.find("default")
        assertNotNull(account)
        assertEquals("user@example.com", account?.email)
        assertEquals("enc_aes_gcm_payload", account?.passwordCiphertext)
        assertTrue(account?.verified == true)

        attachmentDao.upsert(AttachmentEntity(
            sha256 = "abcdef1234567890",
            instanceName = "default",
            name = "sample.txt",
            path = "Attachments/abcdef1234567890/sample.txt",
            bytes = 1024L
        ))

        val att = attachmentDao.find("abcdef1234567890")
        assertNotNull(att)
        assertEquals("sample.txt", att?.name)
        assertEquals(1024L, att?.bytes)
        assertEquals(1, attachmentDao.countByHash("abcdef1234567890"))
    }
}

