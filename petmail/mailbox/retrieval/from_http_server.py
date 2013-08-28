
# I provide a retriever that fetches messages from an HTTP server defined in
# mailbox.server.RetrievalResource. I can either poll or use Server-Sent
# Events to discover new messages. Once I've retrieved them, I delete them
# from the server. I handle transport encryption to hide the message contents
# as I grab them.
