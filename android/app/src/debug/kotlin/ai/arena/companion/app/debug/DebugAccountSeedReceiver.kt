package ai.arena.companion.app.debug

import ai.arena.companion.account.AccountData
import ai.arena.companion.account.AccountVault
import ai.arena.companion.app.KeystoreCipher
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import java.io.File

/**
 * Debug-only receiver used by real-device smoke tests to seed the Android-Keystore-backed
 * account vault without exposing a production entry point. Not packaged in release builds.
 */
class DebugAccountSeedReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val instance = intent.getStringExtra("instance")?.trim().orEmpty().ifBlank { "111" }
        val nickname = intent.getStringExtra("nickname")?.trim().orEmpty()
        val password = intent.getStringExtra("password").orEmpty()
        require(nickname.isNotEmpty()) { "nickname is required" }
        require(password.isNotEmpty()) { "password is required" }
        val nicknameError = AccountData.nicknameError(nickname)
        require(nicknameError.isEmpty()) { nicknameError }

        val instanceDir = File(File(context.filesDir, "instances"), instance)
        val vault = AccountVault(instanceDir, KeystoreCipher())
        vault.save(AccountData(name = nickname, password = password))
        Log.i(TAG, "Seeded account vault for instance=$instance account=${vault.load().redacted()}")
    }

    private companion object {
        const val TAG = "DebugAccountSeed"
    }
}
