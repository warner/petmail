
from twisted.application import service

class LocalDirectoryRendezvousClient(service.MultiService):
    """I manage a rendezvous server which is really just a local directory.
    This allows multiple nodes, all running in sibling basedirs on a shared
    machine, to talk to each other without a network. I add files into the
    directory for 'writes', and poll the directory for reads.
    """
