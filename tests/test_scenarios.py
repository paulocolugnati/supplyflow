"""
EN: Runs every route scenario (tests/scenarios/scenario_*.py) as one test each.
    Each scenario starts in its own Python process, so it gets a fresh app and a fresh
    temporary database, and nothing leaks from one scenario to another.
    A scenario fails when it prints any "FAIL" line, crashes, or checks nothing.
    Run everything from project/:   python -m unittest discover tests
    Run only the scenarios:         python -m unittest tests.test_scenarios -v
PT: Roda cada cenário de rota (tests/scenarios/scenario_*.py) como um teste.
    Cada cenário começa no próprio processo Python, então ganha um app novo e um banco
    temporário novo, e nada vaza de um cenário para outro.
    Um cenário falha quando mostra alguma linha "FAIL", quebra, ou não confere nada.
    Rodar tudo, dentro de project/:   python -m unittest discover tests
    Rodar só os cenários:             python -m unittest tests.test_scenarios -v
"""

import glob
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
# EN: glob.escape: the folder name may contain [brackets], which glob reads as a pattern
# PT: glob.escape: o nome da pasta pode ter [colchetes], que o glob entende como padrão
SCENARIOS = sorted(glob.glob(os.path.join(glob.escape(HERE), "scenarios", "scenario_*.py")))


def run_scenario(path):
    """EN: Run one scenario file and return (exit code, output).
    PT: Roda um arquivo de cenário e devolve (código de saída, saída).
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    # EN: real e-mail sending stays off during tests | PT: o envio real de e-mail fica desligado nos testes
    env.pop("MAIL_USERNAME", None)
    env.pop("MAIL_PASSWORD", None)
    result = subprocess.run([sys.executable, path], cwd=PROJECT, env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=600)
    return result.returncode, result.stdout + result.stderr


class ScenarioTests(unittest.TestCase):
    """EN: One test method per scenario file, created below. | PT: Um método de teste por cenário, criado abaixo."""


def make_test(path):
    def test(self):
        code, output = run_scenario(path)
        failed = [line for line in output.splitlines() if line.startswith("FAIL ")]
        passed = sum(1 for line in output.splitlines() if line.startswith("PASS "))
        self.assertNotIn("Traceback", output, output[-3000:])
        self.assertEqual(code, 0, output[-3000:])
        self.assertEqual(failed, [], "\n".join(failed))
        self.assertGreater(passed, 0, "the scenario checked nothing")
    return test


for _path in SCENARIOS:
    _name = "test_" + os.path.basename(_path)[len("scenario_"):-3]
    setattr(ScenarioTests, _name, make_test(_path))


if __name__ == "__main__":
    unittest.main()
