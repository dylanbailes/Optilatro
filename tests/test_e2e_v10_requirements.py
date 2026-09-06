"""tests/test_e2e_v10_requirements.py — Root test suite forwarding module.

Allows running pytest directly from root:
  pytest tests/test_e2e_v10_requirements.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_VENDOR_TEST_FILE = _ROOT / "vendor" / "balatro-rl" / "tests" / "test_e2e_v10_requirements.py"

_spec = importlib.util.spec_from_file_location("_vendor_e2e_suite", _VENDOR_TEST_FILE)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_vendor_e2e_suite"] = _mod
_spec.loader.exec_module(_mod)

TestTier1_R1_PaceRule = _mod.TestTier1_R1_PaceRule
TestTier1_R2_PortfolioClassification = _mod.TestTier1_R2_PortfolioClassification
TestTier1_R3_OfflineValueModel = _mod.TestTier1_R3_OfflineValueModel
TestTier1_R4_CounterfactualShopSearch = _mod.TestTier1_R4_CounterfactualShopSearch
TestTier2_BoundaryAndCornerCases = _mod.TestTier2_BoundaryAndCornerCases
TestTier3_CrossFeatureInteractions = _mod.TestTier3_CrossFeatureInteractions
TestTier4_RealWorldScenarios = _mod.TestTier4_RealWorldScenarios
reset_v10_params = _mod.reset_v10_params

__all__ = [
    "TestTier1_R1_PaceRule",
    "TestTier1_R2_PortfolioClassification",
    "TestTier1_R3_OfflineValueModel",
    "TestTier1_R4_CounterfactualShopSearch",
    "TestTier2_BoundaryAndCornerCases",
    "TestTier3_CrossFeatureInteractions",
    "TestTier4_RealWorldScenarios",
    "reset_v10_params",
]
