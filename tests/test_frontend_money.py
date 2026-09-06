from pathlib import Path
import shutil
import subprocess
import unittest


class FrontendMoneyTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for frontend money tests")
    def test_service_charge_matches_half_up_rounding(self) -> None:
        app_js = Path(__file__).resolve().parents[1] / "static" / "app.js"
        source = app_js.read_text(encoding="utf-8")
        helper_start = source.index("function decimalToScaledInteger")
        helper_end = source.index("function round(value", helper_start)
        helpers = source[helper_start:helper_end]
        script = helpers + """
const results = [
    percentageMoney('0.15', '10'),
    percentageMoney('2.25', '10'),
    percentageMoney('33.35', '10'),
    roundMoney(0.1 + 0.2),
];
process.stdout.write(JSON.stringify(results));
"""
        completed = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.stdout, "[0.02,0.23,3.34,0.3]")


if __name__ == "__main__":
    unittest.main()
