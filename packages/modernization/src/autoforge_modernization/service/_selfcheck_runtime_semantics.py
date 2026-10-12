"""Verify the Java runtime against REAL golden-master bytes.

Every expected value below was produced by executing the real legacy programs
under GnuCOBOL 3.2 and decoded with the Phase 20 COBOL data dictionary. If the
runtime reproduces these bytes and values, its semantics are pinned to reality
rather than to an assumption.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "packages" / "modernization" / "src"))

from autoforge_modernization.service.java_runtime import render_runtime  # noqa: E402

JAVA_HOME = Path("/opt/homebrew/opt/openjdk@21")

HARNESS = r'''
import cobolrt.CobolRuntime;
import java.math.BigDecimal;

public final class Check {
    private static int failures = 0;

    private static void expect(String label, String actual, String expected) {
        boolean ok = expected.equals(actual);
        System.out.println((ok ? "OK  " : "BAD ") + label
            + " actual=" + actual + " expected=" + expected);
        if (!ok) { failures++; }
    }

    private static byte[] hex(String s) {
        String[] p = s.split(" ");
        byte[] out = new byte[p.length];
        for (int i = 0; i < p.length; i++) {
            out[i] = (byte) Integer.parseInt(p[i], 16);
        }
        return out;
    }

    private static String toHex(byte[] b) {
        StringBuilder sb = new StringBuilder();
        for (byte x : b) { sb.append(String.format("%02x", x)); }
        return sb.toString();
    }

    public static void main(String[] args) {
        byte[] a = hex("00 00 00 50 00 0c");
        expect("overdraft-limit decode",
            CobolRuntime.getPacked(a, 0, 11, 2, true).toPlainString(), "500.00");
        expect("overdraft sign nibble", String.format("%02x", a[5]), "0c");

        byte[] b = hex("00 00 00 00 13 20 0d");
        expect("curr-bal decode",
            CobolRuntime.getPacked(b, 0, 13, 2, true).toPlainString(), "-132.00");

        byte[] c = hex("00 00 00 02 52 50 0c");
        expect("carddemo debit decode",
            CobolRuntime.getPacked(c, 0, 12, 2, true).toPlainString(), "2525.00");
        expect("carddemo filler nibble", String.format("%02x", c[0]), "00");

        byte[] r = CobolRuntime.newRecord(7);
        CobolRuntime.setPacked(r, 0, 12, 2, true, new BigDecimal("2525.00"));
        expect("packed round-trip reproduces real CardDemo bytes",
            toHex(r), "0000000252500c");

        byte[] r2 = CobolRuntime.newRecord(7);
        CobolRuntime.setPacked(r2, 0, 13, 2, true, new BigDecimal("-132.00"));
        expect("packed round-trip -132.00", toHex(r2), "0000000013200d");

        byte[] d = CobolRuntime.newRecord(12);
        CobolRuntime.setDisplay(d, 0, 12, 2, true, new BigDecimal("194.00"));
        expect("display write 194.00", toHex(d),
            "303030303030303139343030");
        expect("display read-back",
            CobolRuntime.getDisplay(d, 0, 12, 2, true).toPlainString(), "194.00");

        byte[] e = hex("30 30 31 39 34 30 7b");
        expect("overpunch positive read",
            CobolRuntime.getDisplay(e, 0, 7, 2, true).toPlainString(), "194.00");
        byte[] f = hex("30 30 31 39 34 30 7d");
        expect("overpunch negative read",
            CobolRuntime.getDisplay(f, 0, 7, 2, true).toPlainString(), "-194.00");

        byte[] g = CobolRuntime.newRecord(10);
        CobolRuntime.setText(g, 0, 10, "20250520");
        expect("text move pad", toHex(g), "20203230323530353230");
        byte[] h = CobolRuntime.newRecord(5);
        CobolRuntime.setText(h, 0, 5, "ABCDEFGH");
        expect("text move truncate", toHex(h), "4142434445");

        byte[] i2 = CobolRuntime.newRecord(7);
        CobolRuntime.setPacked(i2, 0, 9, 2, true, new BigDecimal("123.456"));
        expect("scale truncation",
            CobolRuntime.getPacked(i2, 0, 9, 2, true).toPlainString(), "123.45");

        System.out.println(failures == 0
            ? "ALL RUNTIME SEMANTICS PASS" : "FAILURES=" + failures);
        System.exit(failures == 0 ? 0 : 1);
    }
}
'''


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = root / "cobolrt"
        pkg.mkdir()
        (pkg / "CobolRuntime.java").write_text(render_runtime("cobolrt"))
        (pkg / "Check.java").write_text(HARNESS)
        classes = root / "classes"
        classes.mkdir()
        compile_result = subprocess.run(
            [str(JAVA_HOME / "bin" / "javac"), "-d", str(classes),
             str(pkg / "CobolRuntime.java"), str(pkg / "Check.java")],
            capture_output=True, text=True,
        )
        if compile_result.returncode != 0:
            print("COMPILE FAILED")
            print(compile_result.stderr[:3000])
            return 1
        run_result = subprocess.run(
            [str(JAVA_HOME / "bin" / "java"), "-cp", str(classes), "Check"],
            capture_output=True, text=True,
        )
        print(run_result.stdout)
        print(run_result.stderr[:2000])
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())