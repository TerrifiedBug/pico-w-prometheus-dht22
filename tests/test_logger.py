import sys
from pathlib import Path

# Add firmware directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware"))
from logger import MemoryLogger


def test_memory_logger_trims_entries():
    log = MemoryLogger(max_entries=2)
    log.info("first")
    log.warn("second")
    log.error("third")
    assert len(log.entries) == 2
    assert log.entries[0]['m'] == 'second'
    assert log.entries[1]['m'] == 'third'


def test_memory_logger_filters():
    log = MemoryLogger(max_entries=5)
    # clear any initialization log without adding a new entry
    log.entries.clear()
    log.total_logs = 0
    log.logs_by_level = {"DEBUG": 0, "INFO": 0, "WARN": 0, "ERROR": 0}
    log.info("ok", category="SYSTEM")
    log.error("oops", category="OTA")
    log.debug("debugging", category="SYSTEM")
    errors = log.get_logs(level_filter="ERROR")
    assert len(errors) == 1 and errors[0]['m'] == 'oops'
    system_logs = log.get_logs(category_filter="SYSTEM")
    assert len(system_logs) == 2
