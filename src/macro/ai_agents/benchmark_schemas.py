"""Compatibility imports for the consolidated benchmark contract.

Current inference uses schemas.py and coordinator/aggregation.py. Historical run
records are read as saved data; they are never revalidated against this contract.
"""
from .schemas import (
    SCHEMA_VERSION as VERSION, SCHEMAS, StrictModel, PreferenceFinding,
    BenchmarkAttributeFinding, BenchmarkPreferenceAssessment as PreferenceAssessment,
    BenchmarkAttributeAssessment as AttributeAssessment, BenchmarkSingleAssessment as SingleAssessment,
)
from macro.coordinator.aggregation import comparisons, choose, aggregate
