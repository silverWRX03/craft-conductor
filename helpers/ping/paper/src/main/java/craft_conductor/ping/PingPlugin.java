package craft_conductor.ping;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

import org.bukkit.entity.Player;
import org.bukkit.plugin.java.JavaPlugin;

/**
 * Craft Conductor Ping: every 5 seconds writes each online player's ping to
 * {@code .craft-conductor/ping.json} in the server's working folder, for Craft Conductor to show.
 * It writes nothing else, opens no port and adds no command.
 */
public final class PingPlugin extends JavaPlugin {
    private static final long INTERVAL_TICKS = 100L; // 5 seconds
    private static final String FOLDER = ".craft-conductor";
    private static final String FILE = "ping.json";

    private final AtomicBoolean warned = new AtomicBoolean(false);
    private Path folder;

    @Override
    public void onEnable() {
        folder = Path.of("").toAbsolutePath().resolve(FOLDER);
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
        getServer().getScheduler().runTaskAsynchronously(this, () -> write(now, pings));
    }

    private synchronized void write(long now, Map<String, Integer> pings) {
        Path tmp = null;
        try {
            Files.createDirectories(folder);
            tmp = folder.resolve(FILE + ".tmp");
            Files.write(tmp, toJson(now, pings).getBytes(StandardCharsets.UTF_8));
            Path target = folder.resolve(FILE);
            try {
                Files.move(tmp, target, StandardCopyOption.ATOMIC_MOVE);
            } catch (AtomicMoveNotSupportedException e) {
                Files.move(tmp, target, StandardCopyOption.REPLACE_EXISTING);
            }
            tmp = null;
        } catch (IOException | RuntimeException e) {
            if (warned.compareAndSet(false, true)) {
                getLogger().warning("Craft Conductor Ping: can't write " + FOLDER + "/" + FILE + " (" + e + ")");
            }
        } finally {
            if (tmp != null) {
                try {
                    Files.deleteIfExists(tmp);
                } catch (IOException ignored) {
                    // nothing more to do
                }
            }
        }
    }

    static String toJson(long now, Map<String, Integer> pings) {
        StringBuilder sb = new StringBuilder(64 + pings.size() * 24);
        sb.append("{\"version\": 1, \"time\": ").append(now).append(", \"players\": {");
        boolean first = true;
        for (Map.Entry<String, Integer> e : pings.entrySet()) {
            if (!first) {
                sb.append(", ");
            }
            first = false;
            quote(sb, e.getKey());
            sb.append(": ").append(e.getValue());
        }
        return sb.append("}}\n").toString();
    }

    /** A JSON string literal: quotes, backslashes and control characters escaped. */
    private static void quote(StringBuilder sb, String s) {
        sb.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20 || c == 0x7f || Character.isSurrogate(c) && !validSurrogate(s, i)) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
            }
        }
        sb.append('"');
    }

    private static boolean validSurrogate(String s, int i) {
        char c = s.charAt(i);
        if (Character.isHighSurrogate(c)) {
            return i + 1 < s.length() && Character.isLowSurrogate(s.charAt(i + 1));
        }
        return i > 0 && Character.isHighSurrogate(s.charAt(i - 1));
    }
}
