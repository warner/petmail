
# I manage an HTTP mailbox server that can accept messages sent by
# petmail.mailbox.delivery.http . I define a ServerResource which accepts the
# POSTs and delivers their msgA to a Mailbox.

# the Mailbox object decrypts msgA to get msgB, decrypts the TID, looks up a
# Transport, then dispatches msgB to the transport

# the Transport queues the message somewhere, maybe on disk.

# an HTTP "RetrievalResource" is used by remote clients to pull their
# messages from the Transport. It offers polling and subscription. The
# corresponding client code lives in mailbox.retrieval.from_http_server .

# when using mailbox.retrieval.direct_http, we don't use a RetrievalResource:
# the direct_http retriever subscribes directly to the Transport.
