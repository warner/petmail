
# I know how to "retrieve" messages from an in-process HTTP server, listening
# on the same web server that hosts our node's API and frontend. I am used by
# nodes which have external IP addresses, or for internal/development
# testing.

# reach up to the Client, find the web interface, attach a
# ..server.http_server.ServerResource to "/inbox" (if one isn't already
# there). Find/create our Transport, subscribe to it, so that inbound
# messages are delivered here to us. In this mode, there is no
# RetrievalResource.
