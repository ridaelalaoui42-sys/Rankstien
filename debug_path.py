import pinterest_automation
import inspect
print(f"Location: {inspect.getfile(pinterest_automation)}")
from pinterest_automation import health_monitor
print(f"Health Monitor Location: {inspect.getfile(health_monitor)}")
