import sys
import os

# Append project root to sys.path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from src.production_report import ValidationReporter

reporter = ValidationReporter('1368973312', 'L1')
reporter.step6_compile_report()
print("Report recompiled!")
