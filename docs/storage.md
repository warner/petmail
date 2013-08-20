Storage
=======

To store and share files, each client must contract with one or more `storage
servers`. This is optional, however clients will be unable to use file
transfer, backup, synchronization, sharing, or publishing unless a storage
server is configured.

Storage servers are a lot like Mailboxes, except:

* Storage servers are only writable by their owner, and might be readable by
  others. Mailboxes are only readable by their owner, and may be written to
  by others.
* Storage servers hold data for long periods of time (until the owner deletes
  it, or their contract expires). Mailboxes are allowed to delete items after
  a few days or weeks.

Sharing and Publishing
----------------------

Some storage servers offer the ability to share files with other users,
and/or publish them to the entire world. Not all servers provide this
feature. Bandwidth costs may be harder to control when this feature is used.
Publishing a file to the world allows arbitrary downloads, which will
generally be charged to the owner of the storage account. If the server does
not provide a sufficiently flexible access control policy, share-with-others
may enable arbitrary download of ciphertext, incurring similar costs. Some
server types may enable pre-set cost limits or active monitoring of
downloads, so the client node can unpublish the file after a cost threshold
has been reached, rather than allow unlimited costs.

Renting a Storage Server
------------------------

Clients arrange to rent storage space. As with Mailboxes, the process is
determined by the storage provider, but results in a `storage offer string`
that will be pasted into the client node or passed to the ``petmail storage
add $OFFER`` CLI command.

Non-Petmail services like S3 or Dropbox can be used as storage servers. In
this case, offer strings are not used. Instead, the service credentials must
be added by running e.g. ``petmail storage add s3`` with the AWS keyid and
secret.
