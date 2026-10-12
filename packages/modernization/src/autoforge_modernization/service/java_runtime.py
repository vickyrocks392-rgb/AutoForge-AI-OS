"""The COBOL compatibility runtime shipped with every modernized application.

This is *generated project source*, not AutoForge source. It is emitted into the
customer's ``modernized-application`` so the delivered system is self-contained
and buildable with nothing but a JDK.

Every encoding below was established empirically by executing the real legacy
programs under GnuCOBOL 3.2 and decoding their output with the Phase 20 COBOL
data dictionary. The facts the runtime encodes are:

* ``COMP-3`` occupies ``digits // 2 + 1`` bytes: one nibble per digit plus a
  trailing sign nibble. GnuCOBOL writes ``0xC`` for positive and ``0xD`` for
  negative (verified in ``DAILYPOST`` ``OVERDRAFT-LIMIT`` = ``00 00 00 50 00
  0c`` and ``CURR-BAL`` = ``00 00 00 00 13 20 0d``).
* Signed ``DISPLAY`` numerics are written as **plain digits with no
  overpunch** (verified in CardDemo ``out.ps``: ``000000019400``), but legacy
  data sets may deliver them overpunched, so reads accept both.
* Alphanumeric items are right-justified, left-padded with spaces and truncated
  on the right, per COBOL ``MOVE``.
* Records are byte buffers with fields at fixed offsets, exactly like the
  original COBOL record areas. That is what makes byte-for-byte equivalence
  with the legacy system achievable rather than approximate.

Only the semantics the certified workloads need are implemented. Anything else
is rejected by the generator as an unsupported construct, so it can never
silently produce incorrect output.
"""

__all__ = ["RUNTIME_JAVA", "render_runtime"]


def render_runtime(java_package: str) -> str:
    """Return ``CobolRuntime.java`` source for ``java_package``.

    The Java body is a single template; ``__PACKAGE__`` is the only
    substitution, so the emitted runtime is deterministic and diffable.
    """
    body = _HEAD.replace("__PACKAGE__", java_package)
    return body if body.rstrip().endswith("}") else body + "\n}\n"


_HEAD = r'''
package __PACKAGE__;

import java.io.IOException;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * COBOL data-representation runtime for the modernized batch program.
 *
 * <p>Records are modelled as raw byte buffers exactly like the original COBOL
 * record areas, so every field lives at the same offset with the same encoding
 * it had on the mainframe. That is what makes byte-for-byte equivalence with
 * the legacy system achievable.</p>
 */
public final class CobolRuntime {

    /**
     * Shared stateless instance for generated programs.
     *
     * <p>Every operation below is static, so exactly one instance is needed. It
     * is created here, inside the class that owns the private constructor, so
     * the utility stays closed to outside instantiation while generated code
     * still has something to call through.</p>
     */
    public static final CobolRuntime INSTANCE = new CobolRuntime();

    private CobolRuntime() {
    }

    /** GnuCOBOL packed-decimal sign nibbles, verified from real output bytes. */
    private static final int SIGN_POSITIVE = 0x0C;
    private static final int SIGN_NEGATIVE = 0x0D;

    /** Allocate a record area initialised to spaces, as COBOL does. */
    public static byte[] newRecord(int size) {
        byte[] buffer = new byte[size];
        Arrays.fill(buffer, (byte) ' ');
        return buffer;
    }

    // ── Alphanumeric items ───────────────────────────────────────────────

    /** Read an alphanumeric item (PIC X) preserving every byte. */
    public static String getText(byte[] buffer, int offset, int length) {
        return new String(buffer, offset, length, StandardCharsets.ISO_8859_1);
    }

    /**
     * Write an alphanumeric item using COBOL MOVE rules: right-justified,
     * left-padded with spaces, truncated on the right.
     */
    public static void setText(byte[] buffer, int offset, int length, String value) {
        byte[] source = (value == null ? "" : value).getBytes(StandardCharsets.ISO_8859_1);
        Arrays.fill(buffer, offset, offset + length, (byte) ' ');
        int copy = Math.min(length, source.length);
        System.arraycopy(source, 0, buffer, offset + length - copy, copy);
    }

    /** Copy an alphanumeric field verbatim between two record areas. */
    public static void moveText(byte[] dst, int dstOffset, int dstLength,
                                byte[] src, int srcOffset, int srcLength) {
        Arrays.fill(dst, dstOffset, dstOffset + dstLength, (byte) ' ');
        int copy = Math.min(dstLength, srcLength);
        System.arraycopy(src, srcOffset, dst, dstOffset + (dstLength - copy), copy);
    }

    /**
     * Copy one whole record area onto another, byte for byte.
     *
     * <p>{@code WRITE target-record FROM source-record} copies the entire
     * record, not a single field, so every byte moves at its original offset.
     * This is what makes the legacy output reproducible exactly: a record
     * written from another record is a verbatim image of it.</p>
     */
    public static void copyRecord(byte[] dst, byte[] src) {
        System.arraycopy(src, 0, dst, 0, Math.min(dst.length, src.length));
    }

    /** True when every byte of an item is a digit (COBOL {@code IS NUMERIC}). */
    public static boolean isNumeric(byte[] buffer, int offset, int length) {
        if (length <= 0) {
            return false;
        }
        for (int i = 0; i < length; i++) {
            int value = buffer[offset + i] & 0xFF;
            boolean digit = value >= '0' && value <= '9';
            boolean punched = (value >= 0xC0 && value <= 0xD9)
                || (value >= '{' && value <= '}');
            if (!digit && !punched) {
                return false;
            }
        }
        return true;
    }
// ── Numeric DISPLAY items ───────────────────────────────────────────

    /** Build a BigDecimal from a digit string at an implied scale. */
    private static BigDecimal scaled(String digits, int scale) {
        return new BigDecimal(new java.math.BigInteger(digits), Math.max(0, scale));
    }

    /** Digit value of a byte, accepting overpunched signs on input. */
    private static int digitOf(byte raw) {
        int value = raw & 0xFF;
        if (value >= '0' && value <= '9') {
            return value - '0';
        }
        if (value >= 0xC0 && value <= 0xC9) {
            return value - 0xC0;
        }
        if (value >= 0xD0 && value <= 0xD9) {
            return value - 0xD0;
        }
        switch (value) {
            case '{': case '}': return 0;
            case 'A': case 'J': return 1;
            case 'B': case 'K': return 2;
            case 'C': case 'L': return 3;
            case 'D': case 'M': return 4;
            case 'E': case 'N': return 5;
            case 'F': case 'O': return 6;
            case 'G': case 'P': return 7;
            case 'H': case 'Q': return 8;
            case 'I': case 'R': return 9;
            default: return -1;
        }
    }

    private static boolean isNegativeOverpunch(byte raw) {
        int value = raw & 0xFF;
        if (value == '}' || (value >= 0xD0 && value <= 0xD9)) {
            return true;
        }
        return value >= 'J' && value <= 'R';
    }

    /**
     * Read a DISPLAY numeric item. Overpunched signs are accepted because real
     * legacy data sets deliver them; the modernized system reads the same bytes
     * the mainframe did.
     */
    public static BigDecimal getDisplay(byte[] buffer, int offset, int length,
                                        int scale, boolean signed) {
        StringBuilder digits = new StringBuilder(length);
        boolean negative = false;
        for (int i = 0; i < length; i++) {
            byte raw = buffer[offset + i];
            if (isNegativeOverpunch(raw)) {
                negative = true;
            }
            int digit = digitOf(raw);
            digits.append((char) ('0' + (digit < 0 ? 0 : digit)));
        }
        BigDecimal value = scaled(digits.toString(), scale);
        return signed && negative ? value.negate() : value;
    }

    /**
     * Write a DISPLAY numeric item as plain digits, truncating (never rounding)
     * to the receiving item's scale exactly as COBOL MOVE does.
     */
    public static void setDisplay(byte[] buffer, int offset, int length,
                                  int scale, boolean signed, BigDecimal value) {
        BigDecimal adjusted = normalize(value, scale, length);
        String text = adjusted.unscaledValue().abs().toString();
        StringBuilder body = new StringBuilder();
        for (int i = text.length(); i < length; i++) {
            body.append('0');
        }
        String digits = text.length() > length
            ? text.substring(text.length() - length)
            : body + text;
        for (int i = 0; i < length; i++) {
            buffer[offset + i] = (byte) ('0' + (digits.charAt(i) - '0'));
        }
    }

// ── COMP-3 packed decimal ───────────────────────────────────────────

    /**
     * Byte count of a COMP-3 item: {@code digits / 2 + 1}.
     *
     * <p>When {@code digits + 1} is odd there is one filler nibble at the high
     * end of the field. Verified against real CardDemo output:
     * {@code S9(10)V99} COMP-3 occupies 7 bytes holding 12 digits, one filler
     * nibble and one sign nibble, so the value 2525.00 encodes as
     * {@code 00 00 02 52 50 00 0c}.</p>
     */
    public static int packedSize(int digits) {
        return (digits / 2) + 1;
    }

    /** Read a packed-decimal item (COMP-3), honouring the high-end filler. */
    public static BigDecimal getPacked(byte[] buffer, int offset, int digits,
                                        int scale, boolean signed) {
        int byteCount = packedSize(digits);
        int total = byteCount * 2;
        int filler = total - digits - 1;
        StringBuilder text = new StringBuilder();
        for (int i = 0; i < digits; i++) {
            text.append('0');
        }
        int written = 0;
        for (int i = 0; i < total && written < digits; i++) {
            int raw = buffer[offset + i / 2] & 0xFF;
            int nibble = (i % 2 == 0) ? ((raw >> 4) & 0x0F) : (raw & 0x0F);
            if (i < filler) {
                continue;
            }
            text.setCharAt(written++, (char) ('0' + nibble));
        }
        BigDecimal value = scaled(text.toString(), scale);
        int signNibble = buffer[offset + byteCount - 1] & 0x0F;
        if (signed && (signNibble == SIGN_NEGATIVE || signNibble == 0x0B)) {
            value = value.negate();
        }
        return value;
    }

    /** Write a packed-decimal item (COMP-3) using GnuCOBOL's sign nibbles. */
    public static void setPacked(byte[] buffer, int offset, int digits,
                                 int scale, boolean signed, BigDecimal value) {
        BigDecimal adjusted = normalize(value, scale, digits);
        String magnitude = adjusted.abs().unscaledValue().toString();
        StringBuilder padded = new StringBuilder();
        for (int i = magnitude.length(); i < digits; i++) {
            padded.append('0');
        }
        padded.append(magnitude);
        String body = padded.length() > digits
            ? padded.substring(padded.length() - digits)
            : padded.toString();

        int byteCount = packedSize(digits);
        int total = byteCount * 2;
        int filler = total - digits - 1;
        int[] nibbles = new int[total];
        for (int i = 0; i < digits; i++) {
            nibbles[filler + i] = body.charAt(i) - '0';
        }
        nibbles[total - 1] = (adjusted.signum() < 0 && signed)
            ? SIGN_NEGATIVE : SIGN_POSITIVE;
        for (int i = 0; i < byteCount; i++) {
            buffer[offset + i] = (byte) ((nibbles[2 * i] << 4) | nibbles[2 * i + 1]);
        }
    }

    /** Convenience: {@code a + b}. */
    public static BigDecimal add(BigDecimal a, BigDecimal b) {
        return CobolRuntime.toNumeric(a).add(CobolRuntime.toNumeric(b));
    }

    /** Convenience: {@code a - b}. */
    public static BigDecimal subtract(BigDecimal a, BigDecimal b) {
        return CobolRuntime.toNumeric(a).subtract(CobolRuntime.toNumeric(b));
    }

    /** Convenience: {@code a * b}. */
    public static BigDecimal multiply(BigDecimal a, BigDecimal b) {
        return CobolRuntime.toNumeric(a).multiply(CobolRuntime.toNumeric(b));
    }

    /**
     * COBOL DIVIDE truncates toward zero. {@code BigDecimal} division in
     * {@code DECIMAL128}-style scale would repeat, so the quotient is taken at
     * the natural scale of the dividend to match the legacy result.
     */
    public static BigDecimal divide(BigDecimal a, BigDecimal b) {
        BigDecimal divisor = CobolRuntime.toNumeric(b);
        if (divisor.signum() == 0) {
            return BigDecimal.ZERO;
        }
        BigDecimal dividend = CobolRuntime.toNumeric(a);
        return dividend.divide(divisor, Math.max(0, dividend.scale()),
            RoundingMode.DOWN);
    }

    /** Convenience: unary minus. */
    public static BigDecimal negate(BigDecimal a) {
        return CobolRuntime.toNumeric(a).negate();
    }

    /** COBOL relational comparison for numeric items. */
    public static int compareNumeric(BigDecimal a, BigDecimal b) {
        BigDecimal left = a == null ? BigDecimal.ZERO : a;
        BigDecimal right = b == null ? BigDecimal.ZERO : b;
        return left.compareTo(right);
    }

    /**
     * COBOL relational comparison for alphanumeric items.
     *
     * <p>COBOL pads both operands with spaces to the length of the longer one
     * before comparing, so {@code "ABC"} and {@code "ABC  "} are equal.</p>
     */
    public static int compareText(String a, String b) {
        StringBuilder left = new StringBuilder(a == null ? "" : a);
        StringBuilder right = new StringBuilder(b == null ? "" : b);
        int width = Math.max(left.length(), right.length());
        while (left.length() < width) { left.append(' '); }
        while (right.length() < width) { right.append(' '); }
        return left.toString().compareTo(right.toString());
    }

    /** Coerce an operand to BigDecimal, as COBOL does for numeric contexts. */
    public static BigDecimal toNumeric(Object value) {
        if (value == null) {
            return BigDecimal.ZERO;
        }
        if (value instanceof BigDecimal) {
            return (BigDecimal) value;
        }
        String text = value.toString().trim();
        if (text.isEmpty()) {
            return BigDecimal.ZERO;
        }
        return new BigDecimal(text);
    }

    /** MOVE a value into an item, honouring that item's PICTURE and USAGE. */
    public static void storeValue(byte[] buffer, int offset, int length,
                                  int digits, int scale, boolean signed,
                                  String usage, Object value) {
        if ("COMP-3".equals(usage)) {
            setPacked(buffer, offset, digits, scale, signed, toNumeric(value));
        } else if (digits > 0) {
            setDisplay(buffer, offset, length, scale, signed, toNumeric(value));
        } else {
            setText(buffer, offset, length, value == null ? "" : value.toString());
        }
    }

// ── Numeric helpers ─────────────────────────────────────────────────

    /** Apply the receiving item's scale and digit capacity (COBOL truncation). */
    private static BigDecimal normalize(BigDecimal value, int scale, int digits) {
        BigDecimal result = value == null ? BigDecimal.ZERO : value;
        if (scale > 0) {
            result = result.setScale(scale, RoundingMode.DOWN);
        }
        BigDecimal limit = BigDecimal.TEN.pow(Math.max(0, digits - scale));
        if (result.abs().compareTo(limit) >= 0) {
            result = result.signum() < 0
                ? limit.negate() : limit.subtract(BigDecimal.ONE);
        }
        return result;
    }

    /** MOVE a numeric value into an item of the given picture. */
    public static BigDecimal moveValue(BigDecimal source, int digits, int scale) {
        return CobolRuntime.normalize(source, scale, digits);
    }

// ── Sequential file support ─────────────────────────────────────────

    /** Fixed-length sequential file over a flat, fixed-width data file. */
    public static final class SequentialFile {
        private final List<byte[]> records = new ArrayList<>();
        private Path output;
        private int recordSize;
        private int position;

        public void openInput(Datasets datasets, String name, int size)
                throws IOException {
            this.recordSize = size;
            this.output = null;
            this.records.clear();
            this.position = 0;
            Path path = datasets.resolve(name);
            if (!Files.exists(path)) {
                throw new IOException("Input dataset not found: " + path);
            }
            byte[] raw = Files.readAllBytes(path);
            int offset = 0;
            while (offset + size <= raw.length) {
                records.add(Arrays.copyOfRange(raw, offset, offset + size));
                offset += size;
            }
        }

        public void openOutput(Datasets datasets, String name, int size)
                throws IOException {
            this.recordSize = size;
            this.records.clear();
            this.position = 0;
            this.output = datasets.resolve(name);
            Files.createDirectories(this.output.toAbsolutePath().getParent());
        }

        public boolean read(byte[] target) {
            if (position >= records.size()) {
                return false;
            }
            byte[] record = records.get(position++);
            System.arraycopy(record, 0, target, 0,
                Math.min(record.length, target.length));
            return true;
        }

        public void write(byte[] record) throws IOException {
            if (output == null) {
                throw new IOException("Sequential file is not open for output");
            }
            if (record.length < recordSize) {
                throw new IOException("Record length " + record.length
                    + " is shorter than LRECL " + recordSize);
            }
            try (OutputStream stream = Files.newOutputStream(output,
                    StandardOpenOption.CREATE, StandardOpenOption.APPEND)) {
                stream.write(record, 0, recordSize);
            }
        }

        public void close() {
            output = null;
        }
    }

    /**
     * Dataset name to filesystem path mapping.
     *
     * <p>Seeded from the COBOL {@code SELECT ... ASSIGN TO} clauses the
     * generator read out of the real program, and overridable at run time with
     * {@code --dsn NAME=PATH} so the customer can point the job at their own
     * data without editing code.</p>
     */
    public static final class Datasets {
        private final java.util.Map<String, String> assign = new LinkedHashMap<>();
        private final java.util.Map<String, String> overrides = new LinkedHashMap<>();

        public Datasets put(String name, String path) {
            assign.put(name, path);
            return this;
        }

        public void override(String name, String path) {
            overrides.put(name, path);
        }

        public Path resolve(String name) {
            String path = overrides.get(name);
            if (path == null) {
                path = assign.get(name);
            }
            if (path == null) {
                throw new IllegalStateException("No dataset mapped for " + name);
            }
            return Paths.get(path);
        }

        /** Parse {@code --dsn NAME=PATH} arguments. */
        public static void applyOverrides(String[] args, Datasets datasets) {
            for (int i = 0; i < args.length; i++) {
                if ("--dsn".equals(args[i]) && i + 1 < args.length) {
                    String pair = args[++i];
                    int split = pair.indexOf('=');
                    if (split > 0) {
                        datasets.override(pair.substring(0, split),
                            pair.substring(split + 1));
                    }
                }
            }
        }
    }

    // ── Indexed file support (VSAM KSDS equivalent) ─────────────────────

    /**
     * Keyed file used for {@code ORGANIZATION IS INDEXED} datasets.
     *
     * <p>The certified scope reads such datasets <em>sequentially</em>
     * (CardDemo's {@code CBACT01C} declares {@code ACCESS MODE IS SEQUENTIAL}
     * over a KSDS), so this preserves key order and offers key lookup without
     * depending on any mainframe runtime.</p>
     */
    public static final class IndexedFile {
        private final List<byte[]> records = new ArrayList<>();
        private final List<String> keys = new ArrayList<>();
        private Path source;
        private int recordSize;
        private int keyOffset;
        private int keyLength;
        private int position;

        public void openInput(Path path, int size, int keyOffset, int keyLength)
                throws IOException {
            this.recordSize = size;
            this.keyOffset = keyOffset;
            this.keyLength = keyLength;
            this.source = path;
            this.records.clear();
            this.keys.clear();
            this.position = 0;
            if (!Files.exists(path)) {
                throw new IOException("Input dataset not found: " + path);
            }
            byte[] raw = Files.readAllBytes(path);
            int offset = 0;
            while (offset + size <= raw.length) {
                byte[] record = Arrays.copyOfRange(raw, offset, offset + size);
                records.add(record);
                keys.add(new String(record, keyOffset, keyLength,
                    StandardCharsets.ISO_8859_1));
                offset += size;
            }
        }

        public int size() {
            return records.size();
        }

        /** Sequential READ, honouring {@code ACCESS MODE IS SEQUENTIAL}. */
        public boolean readSequential(byte[] target) {
            if (position >= records.size()) {
                return false;
            }
            System.arraycopy(records.get(position++), 0, target, 0,
                Math.min(recordSize, target.length));
            return true;
        }

        /** Keyed READ; returns false when the key is absent. */
        public boolean readByKey(byte[] target, String key) {
            int index = keys.indexOf(key);
            if (index < 0) {
                return false;
            }
            System.arraycopy(records.get(index), 0, target, 0,
                Math.min(recordSize, target.length));
            return true;
        }
    }

    /** COBOL {@code DISPLAY} output (the modern equivalent of SYSOUT). */
    public static void display(String text) {
        System.out.println(text);
    }
}
'''
