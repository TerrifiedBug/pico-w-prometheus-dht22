"""
Memory-Efficient Logging System for Pico W

Provides structured logging with circular buffer storage using ~10KB of RAM.
Designed for debugging OTA updates and system operations without disk usage.
"""

import time
import gc


class MemoryLogger:
    """
    Pure memory-based logger with circular buffer and automatic cleanup.

    Uses approximately 10KB of RAM for 150 log entries.
    """

    def __init__(self, max_entries=150, max_memory_bytes=10240):
        """
        Initialize the memory logger.

        Args:
            max_entries (int): Maximum number of log entries to keep
            max_memory_bytes (int): Maximum memory usage in bytes (~10KB)
        """
        self.entries = []
        self.max_entries = max_entries
        self.max_memory_bytes = max_memory_bytes
        self.start_time = time.time()
        self.log_levels = ["DEBUG", "INFO", "WARN", "ERROR"]
        self.categories = ["SYSTEM", "OTA", "SENSOR", "CONFIG", "NETWORK", "HTTP"]

        # Statistics
        self.total_logs = 0
        self.logs_by_level = {"DEBUG": 0, "INFO": 0, "WARN": 0, "ERROR": 0}

        self.log("INFO", "Memory logger initialized", "SYSTEM")

    def log(self, level, message, category="SYSTEM"):
        """
        Add a log entry to the circular buffer.

        Args:
            level (str): Log level (DEBUG, INFO, WARN, ERROR)
            message (str): Log message (will be truncated if too long)
            category (str): Log category for filtering
        """
        # Validate inputs
        if level not in self.log_levels:
            level = "INFO"
        if category not in self.categories:
            category = "SYSTEM"

        # Truncate long messages to save memory
        if len(message) > 80:
            message = message[:77] + "..."

        # Create efficient log entry
        timestamp = int(time.time() - self.start_time)
        entry = {
            't': timestamp,      # Relative timestamp (seconds since boot)
            'l': level,          # Log level
            'c': category,       # Category
            'm': message         # Message
        }

        self.entries.append(entry)
        self.total_logs += 1
        self.logs_by_level[level] += 1

        # Enforce memory limits
        self._enforce_limits()

    def _enforce_limits(self):
        """Enforce memory and entry count limits."""
        # Remove oldest entries if we exceed max count
        while len(self.entries) > self.max_entries:
            self.entries.pop(0)

        # Check memory usage and trim if needed
        current_memory = self._estimate_memory_usage()
        if current_memory > self.max_memory_bytes:
            self._trim_logs()

    def _estimate_memory_usage(self):
        """
        Estimate memory usage of log entries.

        Returns:
            int: Estimated memory usage in bytes
        """
        if not self.entries:
            return 0

        # Sample a few entries to estimate average size
        sample_size = min(10, len(self.entries))
        total_size = 0

        for i in range(sample_size):
            entry = self.entries[i]
            # Rough calculation: dict overhead + string sizes
            size = 100  # Base dict overhead
            size += len(str(entry['t'])) + len(entry['l']) + len(entry['c']) + len(entry['m'])
            total_size += size

        avg_size = total_size / sample_size
        return int(avg_size * len(self.entries))

    def _trim_logs(self):
        """Remove oldest 25% of logs when memory limit is exceeded."""
        trim_count = len(self.entries) // 4
        if trim_count > 0:
            self.entries = self.entries[trim_count:]

    def get_logs(self, level_filter=None, category_filter=None, last_n=None):
        """
        Get filtered log entries.

        Args:
            level_filter (str): Filter by log level (None for all)
            category_filter (str): Filter by category (None for all)
            last_n (int): Return only last N entries (None for all)

        Returns:
            list: Filtered log entries
        """
        filtered_logs = self.entries

        # Apply level filter
        if level_filter and level_filter != "ALL":
            filtered_logs = [log for log in filtered_logs if log['l'] == level_filter]

        # Apply category filter
        if category_filter and category_filter != "ALL":
            filtered_logs = [log for log in filtered_logs if log['c'] == category_filter]

        # Apply count limit
        if last_n and last_n > 0:
            filtered_logs = filtered_logs[-last_n:]

        return filtered_logs

    def get_logs_as_text(self, level_filter=None, category_filter=None, last_n=None):
        """
        Get logs formatted as plain text.

        Returns:
            str: Formatted log text
        """
        logs = self.get_logs(level_filter, category_filter, last_n)

        if not logs:
            return "No logs found matching criteria."

        lines = []
        for log in logs:
            # Format: [+123s] ERROR OTA: Update failed
            timestamp_str = f"+{log['t']}s"
            line = f"[{timestamp_str:>6}] {log['l']:5} {log['c']:7}: {log['m']}"
            lines.append(line)

        return "\n".join(lines)

    def get_statistics(self):
        """
        Get logging statistics.

        Returns:
            dict: Statistics about logging system
        """
        return {
            "total_entries": len(self.entries),
            "total_logged": self.total_logs,
            "memory_usage_bytes": self._estimate_memory_usage(),
            "memory_usage_kb": round(self._estimate_memory_usage() / 1024, 1),
            "uptime_seconds": int(time.time() - self.start_time),
            "logs_by_level": self.logs_by_level.copy(),
            "max_entries": self.max_entries,
            "max_memory_kb": round(self.max_memory_bytes / 1024, 1)
        }

    def clear_logs(self):
        """Clear all log entries."""
        self.entries.clear()
        self.total_logs = 0
        self.logs_by_level = {"DEBUG": 0, "INFO": 0, "WARN": 0, "ERROR": 0}
        self.log("INFO", "Log buffer cleared", "SYSTEM")

    def debug(self, message, category="SYSTEM"):
        """Log a DEBUG message."""
        self.log("DEBUG", message, category)

    def info(self, message, category="SYSTEM"):
        """Log an INFO message."""
        self.log("INFO", message, category)

    def warn(self, message, category="SYSTEM"):
        """Log a WARN message."""
        self.log("WARN", message, category)

    def error(self, message, category="SYSTEM"):
        """Log an ERROR message."""
        self.log("ERROR", message, category)


# Global logger instance
logger = MemoryLogger()

# Convenience functions for global access
def log_debug(message, category="SYSTEM"):
    """Log a DEBUG message using global logger."""
    logger.debug(message, category)

def log_info(message, category="SYSTEM"):
    """Log an INFO message using global logger."""
    logger.info(message, category)

def log_warn(message, category="SYSTEM"):
    """Log a WARN message using global logger."""
    logger.warn(message, category)

def log_error(message, category="SYSTEM"):
    """Log an ERROR message using global logger."""
    logger.error(message, category)

def get_logger():
    """Get the global logger instance."""
    return logger
