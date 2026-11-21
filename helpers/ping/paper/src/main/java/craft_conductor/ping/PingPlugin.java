package craft_conductor.ping;

import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;

import org.bukkit.entity.Player;
import org.bukkit.plugin.java.JavaPlugin;

/**
 * Craft Conductor Ping: every 5 seconds writes each online player's ping to
 * {@code .craft-conductor/ping.json} in the server's working folder, for Craft Conductor to show.
 * It writes nothing else, opens no port and adds no command.
 */
public final class PingPlugin extends JavaPlugin {
    private static final long INTERVAL_TICKS = 100L; // 5 seconds

    private PingFile file;

    @Override
    public void onEnable() {
        file = new PingFile(Path.of("").toAbsolutePath(), getLogger()::warning);
        getLogger().info("Craft Conductor Ping: reporting players' ping to Craft Conductor");
        getServer().getScheduler().runTaskTimer(this, this::collect, INTERVAL_TICKS, INTERVAL_TICKS);
    }

    /** On the server thread: read the pings, then hand the writing to another thread. */
    private void collect() {
        Map<String, Integer> pings = new LinkedHashMap<>();
        for (Player player : getServer().getOnlinePlayers()) {
            pings.put(player.getName(), Math.max(0, player.getPing()));
        }
        long now = System.currentTimeMillis();
        getServer().getScheduler().runTaskAsynchronously(this, () -> file.write(now, pings));
    }
}
