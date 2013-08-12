
# sending side

def create_message(to_pubkey, from_signkey, payload):
    return msgC

def wrap_for_mailbox(mailbox_pubkey, client_id, msgC):
    return msgA

def wrap_for_transport(msgA):
    return "v1" + "%d:%s." % (len(msgA), msgA)


# receiving side

class WireProtocol(protocol.Protocol):
    def dataReceived(self, chunk):
        self.buffer = self.buffer + chunk
        while True:
            if len(self.buffer) > 2:
                if self.buffer[:2] != "v1":
                    print "unknown version string '%s'" % self.buffer[:2]
                    self.loseConnection()
                    return
            mo = re.search(r'^v1(%d)+:', self.buffer)
            if not mo:
                return
            header_length = 2+len(mo.group(1))+1
            body_length = int(mo.group(1))
            if len(self.buffer) < header_length+body_length+1:
                return
            body = self.buffer[header_length:header_length+body_length]
            self.buffer = self.buffer[header_length+body_length+1:]
            try:
                self.transportMessageReceived(body)
            except:
                log("bad msgA")
                raise

        def transportMessageReceived(self, msgA):
            to_key = msgA[0:32]
            from_key = msgA[32:64]
            nonce = msgA[64:84]
            encB = msg[84:]
            if to_key != self.mailbox_pubkey:
                raise WrongKeyError("mailbox message sent to non-mailbox key")
            msgB = unbox(self.mailbox_privkey, from_key, nonce, encB)
            self.msgBReceived(msgB)

        def msgBReceived(self, msgB):
            clientID = msgB[0:32]
            msgC = msgB[32:]
            recipient = self.recipients[clientID]
            self.queueForRecipient(recipient, msgC)

        def queueForRecipient(self, recipient, msgC):
            self.queues[recipient].append(msgC)

# a Protocol will split versioned netstrings from the input stream
