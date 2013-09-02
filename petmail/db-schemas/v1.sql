
-- note: anything which isn't an boolean, integer, or human-readable unicode
-- string, (i.e. binary strings) will be stored as hex

CREATE TABLE `version`
(
 `version` INTEGER -- contains one row, set to 1
);

CREATE TABLE `node` -- contains one row
(
 `webhost` STRING, -- hostname or IP address to advertise in URLs
 `webport` STRING -- twisted service descriptor string, e.g. "tcp:0"
);

CREATE TABLE `services`
(
 `name` STRING
);

CREATE TABLE `webapi_opener_tokens`
(
 `token` STRING
);

CREATE TABLE `webapi_access_tokens`
(
 `token` STRING
);

CREATE TABLE `mailbox_server_config` -- contains exactly one row
(
 -- .transport_privkey, TID_private_key, local_TID0, local_TID_tokenid
 `private_descriptor_json` STRING,
 `enable_retrieval` INT -- for public servers
);

CREATE TABLE `mailboxes` -- one per mailbox
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  -- give sender_desc to peers, tells them how to send us messages
  -- .type, (.url), .transport_pubkey
  -- we will add .STID before sending
 `sender_descriptor_json` STRING,
 -- private_descriptor is for recipient (us), tells us how to read our inbox
 -- .type, .TID0, (.url), (retrieval credentials)
 `private_descriptor_json` STRING
);

CREATE TABLE `client_profile` -- contains one row
(
 `name` STRING,
 `icon_data` STRING
);

CREATE TABLE `invitations` -- data on all pending invitations
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,

 `petname` STRING,

 -- these are only used during the invitation process, then discarded
 `code` STRING,
 `inviteKey` STRING, -- Ed25519 signing key
 `inviteID` STRING, -- Ed25519 verifying key
 `myTempPrivkey` STRING, -- Curve25519 privkey (ephemeral)
 `theirTempPubkey` STRING, -- Curve25519 pubkey (ephemeral)
 -- these track the state of the invitation process
 `myMessages` STRING, -- r0:hex,r0-hex of all my sent messages
 `theirMessages` STRING, -- r0:hex,r0-hex of all processed inbound messages
 `nextExpectedMessage` INTEGER,

 -- these two are retained long-term, in the addressbook entry
 `mySigningKey` STRING, -- Ed25519 privkey (long-term), for this peer
 `addressbook_id` INTEGER, -- to correlate with an addressbook entry

 -- my (public) record: .channel_pubkey, .CID_key,
 --  .transports[]: .STID, .transport_pubkey, .type, .url
 `my_channel_record` STRING,
 -- my private record: .my_signkey, .my_CID_key, .my_{old,new}_channel_privkey,
 --  .transport_ids (points to 'transports' table)
 `my_private_channel_data` STRING
);

CREATE TABLE `addressbook`
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT, -- the channelID

 -- our private notes and decisions about them
 `petname` STRING,
 `acked` INTEGER,
 -- public notes about them

 -- things used to send outbound messages
    -- these three are shared among all of the recipient's mailboxes
 `next_outbound_seqnum` INTEGER,
 `my_signkey` STRING,
 `their_channel_record_json` STRING, -- .channel_pubkey, .CID_key, .transports

 -- things used to handle inbound messages
 `my_CID_key` STRING,
 `next_CID_token` STRING,
 `highest_inbound_seqnum` INTEGER,
 `my_old_channel_privkey` STRING,
 `my_new_channel_privkey` STRING,
 `they_used_new_channel_key` INTEGER,
 `their_verfkey` STRING -- from their invitation message
);

CREATE TABLE `inbound_messages`
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `cid` INTEGER, -- points to addressbook entry
 `seqnum` INTEGER, -- scoped to channel
 `payload_json` STRING
);
