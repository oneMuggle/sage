package ai.arena.companion

import ai.arena.companion.identity.ConversationIdentity
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ConversationIdentityTest {

    private val uuid = "0A1B2C3D-4E5F-6071-8293-A4B5C6D7E8F9"

    @Test
    fun `uuid path is lowercased and normalized`() {
        assertEquals(
            "https://arena.ai/agent/${uuid.lowercase()}",
            ConversationIdentity.route("https://arena.ai/agent/$uuid/")
        )
    }

    @Test
    fun `explicit 443 is accepted and other ports rejected`() {
        assertEquals("https://arena.ai/agent", ConversationIdentity.route("https://arena.ai:443/agent"))
        assertNull(ConversationIdentity.route("https://arena.ai:8443/agent"))
    }

    @Test
    fun `non https userinfo and foreign hosts rejected`() {
        assertNull(ConversationIdentity.route("http://arena.ai/agent"))
        assertNull(ConversationIdentity.route("https://u:p@arena.ai/agent"))
        assertNull(ConversationIdentity.route("https://evil.arena.ai/agent"))
        assertNull(ConversationIdentity.route("https://arena.ai/agent/not-a-uuid"))
    }

    @Test
    fun `demo host keeps its own conversation form`() {
        assertEquals("https://arena-demo.local/agent/demo-1", ConversationIdentity.route("https://arena-demo.local/agent/demo-1"))
        assertNull(ConversationIdentity.route("https://arena-demo.local/agent/demo-0"))
        assertNull(ConversationIdentity.created("https://arena-demo.local/agent/demo-1"))
    }

    @Test
    fun `same compares canonical form`() {
        assertTrue(ConversationIdentity.same("https://arena.ai/agent/$uuid", "https://arena.ai/agent/${uuid.lowercase()}/"))
        assertFalse(ConversationIdentity.same("https://arena.ai/agent", "https://arena.ai/agent/$uuid"))
    }

    @Test
    fun `transition only from new conversation`() {
        assertTrue(ConversationIdentity.isTransition("https://arena.ai/agent", "https://arena.ai/agent/$uuid"))
        assertFalse(ConversationIdentity.isTransition("https://arena.ai/agent/$uuid", "https://arena.ai/agent/$uuid"))
    }
}
