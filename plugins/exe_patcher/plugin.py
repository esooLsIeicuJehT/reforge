from core.plugin_manager import BasePlugin

class EXEPatcherPlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self.name = "EXE Patcher"
        self.description = "PE binary patcher (AOB, hosts, services)"

    def initialize(self, main_window):
        pass

    def shutdown(self):
        pass