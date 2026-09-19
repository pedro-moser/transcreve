import builtins
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


class OptionalDependencyTests(unittest.TestCase):
    def test_app_module_imports_without_torch(self):
        """The base installation must start without the optional stem packages."""
        original_import = builtins.__import__

        def import_without_torch(name, *args, **kwargs):
            if name == "torch" or name.startswith("torch."):
                raise ModuleNotFoundError("No module named 'torch'")
            return original_import(name, *args, **kwargs)

        sys.modules.pop("services.separation_service", None)
        with patch("builtins.__import__", side_effect=import_without_torch):
            module = importlib.import_module("services.separation_service")

        self.assertTrue(hasattr(module, "SeparationService"))


if __name__ == "__main__":
    unittest.main()
