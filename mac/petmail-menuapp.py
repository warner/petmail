import rumps

rumps.debug_mode(True)

class PetmailLauncher(rumps.App):
    def __init__(self):
        super(PetmailLauncher, self).__init__("Petmail")
        self.menu = ["Open", "Launch Daemon", "Restart Daemon", "Stop Daemon"]

    @rumps.clicked("Open")
    def open(self, _):
        print "petmail open"

    @rumps.clicked("Launch Daemon")
    def launch(self, _):
        print "petmail start"

    @rumps.clicked("Restart Daemon")
    def restart(self, _):
        print "petmail restart"

    @rumps.clicked("Stop Daemon")
    def stop(self, _):
        print "petmail stop"


if __name__ == '__main__':
    PetmailLauncher().run()
