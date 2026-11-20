package craft_conductor.ping;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

/**
 * {@code .craft-conductor/ping.json} in the server's working folder, shared by every platform's helper:
 * {@code {"version": 1, "time": <unix ms>, "players": {"<name>": <ms>}}}, written to a temporary file in
 * the same folder and renamed over the old one, so Craft Conductor never reads half a file.
 */
final class PingFile {
    static final String FOLDER = ".craft-conductor";
    static final String FILE = "ping.json";

    private final Path folder;
    private final Consumer<String> warn;
    private final AtomicBoolean warned = new AtomicBoolean(false);

    /** {@code workingFolder}: the server's own folder; {@code warn}: logs a warning (said once, not every time). */
    PingFile(Path workingFolder, Consumer<String> warn) {
        this.folder = workingFolder.resolve(FOLDER);
        this.warn = warn;
    }

    synchronized void write(long now, Map<String, Integer> pings) {
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
            failed(e);
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

    /** The file can't be written (or the pings can't be read): said the first time only. */
    void failed(Throwable e) {
        if (warned.compareAndSet(false, true)) {
            warn.accept("Craft Conductor Ping: can't write " + FOLDER + "/" + FILE + " (" + e + ")");
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
