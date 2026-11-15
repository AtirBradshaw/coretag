import platform

from ..util import safe


def cpu_name():
    """platform.processor() on Windows gives 'Intel64 Family 6 Model...';
    the registry has the marketing name people recognise."""
    if platform.system() == "Windows":
        def reg():
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                               r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        name = safe(reg)
        if name:
            return name
    return platform.processor() or None


def collect_system():
    # deliberately no hostname, username or IP address
    return {
        "os": platform.system(),
        "os_version": platform.release() + " (" + platform.version() + ")",
        "cpu": cpu_name(),
        "python": platform.python_version(),
    }
