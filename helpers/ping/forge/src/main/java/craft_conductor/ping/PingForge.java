package craft_conductor.ping;

import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraftforge.fml.common.Mod;
import net.minecraftforge.server.ServerLifecycleHooks;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Craft Conductor Ping for Forge 1.20.1 (server only): every 5 seconds writes each online player's ping to
 * {@code .craft-conductor/ping.json} in the server's working folder, for Craft Conductor to show.
 * It writes nothing else, opens no port, adds no command and registers no network channel, so players
 * without it (a plain Minecraft client) still join.
 */
@Mod("craft_conductor_ping")
public final class PingForge {
    private static final long INTERVAL_SECONDS = 5;
    private static final Logger LOG = LoggerFactory.getLogger("craft_conductor_ping");

    /** A reading asked of the server thread and not written yet: a busy server gets no second one. */
    private final AtomicBoolean pending = new AtomicBoolean(false);
    private final PingFile file;
    private final ScheduledExecutorService scheduler;

    public PingForge() {
        file = new PingFile(Path.of("").toAbsolutePath(), LOG::warn);
        scheduler = Executors.newSingleThreadScheduledExecutor(task -> {
            Thread thread = new Thread(task, "Craft Conductor Ping");
            thread.setDaemon(true);
            return thread;
        });
        LOG.info("Craft Conductor Ping: reporting players' ping to Craft Conductor");
        scheduler.scheduleWithFixedDelay(this::tick, INTERVAL_SECONDS, INTERVAL_SECONDS, TimeUnit.SECONDS);
    }

    /** On the helper's own thread: ask the server thread for the pings, then write them here. */
    private void tick() {
        try {
            MinecraftServer server = ServerLifecycleHooks.getCurrentServer();
            if (server == null || !pending.compareAndSet(false, true)) {
                return; // (no server yet, or the last reading isn't done)
            }
            CompletableFuture.supplyAsync(() -> collect(server), server)
                    .thenAcceptAsync(pings -> file.write(System.currentTimeMillis(), pings), scheduler)
                    .whenComplete((done, error) -> {
                        pending.set(false);
                        if (error != null) {
                            file.failed(error);
                        }
                    });
        } catch (Throwable e) { // (the next tick still runs: a scheduled task that throws is never run again)
            pending.set(false);
            file.failed(e);
        }
    }

    /**
     * On the server thread: each online player's name and latency, the value the tab list shows (on 1.20.1
     * a field of the player, which the keep-alive answers update; from 1.20.2 it is on the connection).
     */
    private static Map<String, Integer> collect(MinecraftServer server) {
        Map<String, Integer> pings = new LinkedHashMap<>();
        for (ServerPlayer player : server.getPlayerList().getPlayers()) {
            if (player.connection != null) { // (a player some mod made without a connection: no ping)
                pings.put(player.getScoreboardName(), Math.max(0, player.latency));
            }
        }
        return pings;
    }
}
