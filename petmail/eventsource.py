from twisted.protocols import basic

class EventSourceParser(basic.LineOnlyReceiver):
    delimiter = "\n"

    def __init__(self, handler):
        self.current_field = None
        self.current_lines = []
        self.handler = handler

    def lineReceived(self, line):
        if not line:
            # blank line ends the field
            self.fieldReceived(self.current_field,
                               "\n".join(self.current_lines))
            self.current_field = None
            self.current_lines[:] = []
            return
        if self.current_field is None:
            self.current_field, data = line.split(": ", 1)
            self.current_lines.append(data)
        else:
            self.current_lines.append(line)

    def fieldReceived(self, name, data):
        self.handler(name, data)

