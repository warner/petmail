
-- note: anything which isn't an boolean, integer, or human-readable unicode
-- string, (i.e. binary strings) will be stored as hex

CREATE TABLE `version`
(
 `version` INTEGER -- contains one row, set to 1
);

CREATE TABLE `node` -- contains one row
(
 `listenport` STRING, -- twisted service descriptor string, e.g. "tcp:1234"
 `baseurl` STRING
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

-- These three mailbox_server_* tables (and retrieval_replay_tokens) are used
-- the MailboxServer that lives inside each node. This server is only exposed
-- to the outside world if requested, generally because the node has a stable
-- routeable address. The server always accepts messages for the local agent,
-- but the agent will only advertise that fact if the server is exposed to
-- the outside world. The server will also accept messages for other (remote)
-- agents if those transports are allocated: this is how servers-for-hire
-- work.

CREATE TABLE `mailbox_server_config` -- contains exactly one row
(
 -- .transport_privkey, TT_private_key, local_TT0, local_TTID
 `mailbox_config_json` STRING
);

CREATE TABLE `mailbox_server_transports` -- one row per user we support
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `TTID` STRING, -- transport token ID, used during delivery
 `TT0` STRING, -- initial transport token, given to recipient
 `RT` STRING, -- retrieval token
 `symkey` STRING
);
CREATE UNIQUE INDEX `TTID` ON `mailbox_server_transports` (`TTID`);
CREATE UNIQUE INDEX `RT` ON `mailbox_server_transports` (`RT`);

CREATE TABLE `mailbox_server_messages`
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `tid` INTEGER,
 `fetch_token` STRING,
 `delete_token` STRING,
 `length` INTEGER,
 `msgC` STRING
);
CREATE INDEX `tid_token` ON `mailbox_server_messages` (`tid`);
CREATE UNIQUE INDEX `fetch_token` ON `mailbox_server_messages` (`fetch_token`);
CREATE UNIQUE INDEX `delete_token` ON `mailbox_server_messages` (`delete_token`);

CREATE TABLE `retrieval_replay_tokens`
(
 `timestamp` INT,
 `pubkey` STRING
);
CREATE UNIQUE INDEX `timestamp` ON `retrieval_replay_tokens` (`timestamp`);
CREATE UNIQUE INDEX `token` ON `retrieval_replay_tokens` (`timestamp`, `pubkey`);

-- The following tables are owned by the Agent, not the Server.

CREATE TABLE `relay_servers`
(
 `descriptor_json` STRING
);

CREATE TABLE `mailboxes` -- one per remote mailbox (no local mailboxes here)
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `mailbox_record_json` STRING
);

CREATE TABLE `agent_profile` -- contains one row
(
 `advertise_local_mailbox` INTEGER,
 `name` STRING,
 `icon_data` STRING
);

CREATE TABLE `invitations` -- data on all pending invitations
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,

 -- these are only used during the invitation process, then discarded
 `code` STRING,
 `invite_key` STRING, -- Ed25519 signing key
 `inviteID` STRING, -- Ed25519 verifying key
 `my_temp_privkey` STRING, -- Curve25519 privkey (ephemeral)
 `their_temp_pubkey` STRING, -- Curve25519 pubkey (ephemeral)
 -- these track the state of the invitation process
 `my_messages` STRING, -- r0:hex,r0-hex of all my sent messages
 `their_messages` STRING, -- r0:hex,r0-hex of all processed inbound messages
 `next_expected_message` INTEGER,

 -- these two are retained long-term, in the addressbook entry
 `my_signkey` STRING, -- Ed25519 privkey (long-term), for this peer
 `addressbook_id` INTEGER, -- to correlate with an addressbook entry

 -- they'll get this payload in M2
 --  .channel_pubkey, .CID_key,
 --  .transports[]: .STT, .transport_pubkey, .type, .url
 `payload_for_them_json` STRING,
 -- my private record: .my_signkey, .my_CID_key, .my_{old,new}_channel_privkey,
 --  .transport_ids (points to 'transports' table), .petname,
 --  .invitation_context
 `my_private_invitation_data` STRING
);

CREATE TABLE `addressbook`
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT, -- the channelID

 -- our private notes and decisions about them
 `petname` STRING,
 `acked` INTEGER,
 `invitation_context_json` STRING, -- .when_invited, .when_accepted, .code
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
