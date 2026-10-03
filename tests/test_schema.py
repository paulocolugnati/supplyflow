"""
EN: Runs scripts/check_schema.py (the database rules: CHECKs, foreign keys, cascades,
    unique indexes) as part of the test suite. It uses an in-memory database.
PT: Roda o scripts/check_schema.py (as regras do banco: CHECKs, chaves estrangeiras,
    cascatas, índices únicos) como parte da suíte de testes. Usa um banco em memória.
"""

import os
import subprocess
import sys
import unittest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SchemaTest(unittest.TestCase):

    def test_schema_rules(self):
        result = subprocess.run([sys.executable, os.path.join("scripts", "check_schema.py")], cwd=PROJECT,
                                capture_output=True, text=True, encoding="utf-8",
                                env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr[-2000:])
        self.assertIn(" 0 failed", result.stdout)


if __name__ == "__main__":
    unittest.main()
