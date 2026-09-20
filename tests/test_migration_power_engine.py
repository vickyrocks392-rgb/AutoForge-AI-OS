"""Root test runner for 18-COMMERCIAL-D Code Migration Power Engine tests."""

import importlib.util
from pathlib import Path

target_file = Path(__file__).parent.parent / "packages" / "power_engines" / "tests" / "test_migration_power_engine.py"
spec = importlib.util.spec_from_file_location("pe_migration_tests", str(target_file))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

TestMigrationPowerEngine = mod.TestMigrationPowerEngine

if __name__ == "__main__":
    import unittest
    unittest.main()
