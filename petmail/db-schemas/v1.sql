
-- note: anything which isn't an boolean, integer, or human-readable unicode
-- string, (i.e. binary strings) will be stored as hex

CREATE TABLE `version`
(
 `version` INTEGER -- contains one row, set to 1
);

CREATE TABLE `node` -- contains one row
(
 `listenport` VARCHAR, -- twisted service descriptor string, e.g. "tcp:1234"
 `baseurl` VARCHAR
);

CREATE TABLE `services`
(
 `name` VARCHAR
);

CREATE TABLE `webapi_opener_tokens`
(
 `token` VARCHAR
);

CREATE TABLE `webapi_access_tokens`
(
 `token` VARCHAR
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
 `mailbox_config_json` VARCHAR
);

CREATE TABLE `mailbox_server_transports` -- one row per user we support
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `TTID` VARCHAR, -- transport token ID, used during delivery
 `TT0` VARCHAR, -- initial transport token, given to recipient
 `RT` VARCHAR, -- retrieval token
 `symkey` VARCHAR
);
CREATE UNIQUE INDEX `TTID` ON `mailbox_server_transports` (`TTID`);
CREATE UNIQUE INDEX `RT` ON `mailbox_server_transports` (`RT`);

CREATE TABLE `mailbox_server_messages`
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `tid` INTEGER,
 `fetch_token` VARCHAR,
 `delete_token` VARCHAR,
 `length` INTEGER,
 `msgC` VARCHAR
);
CREATE INDEX `tid_token` ON `mailbox_server_messages` (`tid`);
CREATE UNIQUE INDEX `fetch_token` ON `mailbox_server_messages` (`fetch_token`);
CREATE UNIQUE INDEX `delete_token` ON `mailbox_server_messages` (`delete_token`);

CREATE TABLE `retrieval_replay_tokens`
(
 `timestamp` INT,
 `pubkey` VARCHAR
);
CREATE UNIQUE INDEX `timestamp` ON `retrieval_replay_tokens` (`timestamp`);
CREATE UNIQUE INDEX `token` ON `retrieval_replay_tokens` (`timestamp`, `pubkey`);

-- The following tables are owned by the Agent, not the Server.

CREATE TABLE `relay_servers`
(
 `descriptor_json` VARCHAR
);

CREATE TABLE `mailboxes` -- one per remote mailbox (no local mailboxes here)
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `mailbox_record_json` VARCHAR
);

CREATE TABLE `agent_profile` -- contains one row
(
 `advertise_local_mailbox` INTEGER,
 `name` VARCHAR,
 `icon_data` VARCHAR
);

CREATE TABLE `invitations` -- data on all pending invitations
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,

 -- these are only used during the invitation process, then discarded
 `code` VARCHAR,
 `invite_key` VARCHAR, -- Ed25519 signing key
 `inviteID` VARCHAR, -- Ed25519 verifying key
 `my_temp_privkey` VARCHAR, -- Curve25519 privkey (ephemeral)
 `their_temp_pubkey` VARCHAR, -- Curve25519 pubkey (ephemeral)
 -- these track the state of the invitation process
 `my_messages` VARCHAR, -- r0:hex,r0-hex of all my sent messages
 `their_messages` VARCHAR, -- r0:hex,r0-hex of all processed inbound messages
 `next_expected_message` INTEGER,

 -- these two are retained long-term, in the addressbook entry
 `my_signkey` VARCHAR, -- Ed25519 privkey (long-term), for this peer
 `addressbook_id` INTEGER, -- to correlate with an addressbook entry

 -- they'll get this payload in M2
 --  .channel_pubkey, .CID_key,
 --  .transports[]: .STT, .transport_pubkey, .type, .url
 `payload_for_them_json` VARCHAR,
 -- my private record: .my_signkey, .my_CID_key, .my_{old,new}_channel_privkey,
 --  .transport_ids (points to 'transports' table), .petname,
 --  .invitation_context
 `my_private_invitation_data` VARCHAR
);

CREATE TABLE `addressbook`
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT, -- the channelID

 -- our private notes and decisions about them
 `petname` VARCHAR,
 `acked` INTEGER,
 `invitation_context_json` VARCHAR, -- .when_invited, .when_accepted, .code
 -- public notes about them

 -- things used to send outbound messages
    -- these three are shared among all of the recipient's mailboxes
 `next_outbound_seqnum` INTEGER,
 `my_signkey` VARCHAR,
 `their_channel_record_json` VARCHAR, -- .channel_pubkey, .CID_key, .transports

 -- things used to handle inbound messages
 `my_CID_key` VARCHAR,
 `next_CID_token` VARCHAR,
 `highest_inbound_seqnum` INTEGER,
 `my_old_channel_privkey` VARCHAR,
 `my_new_channel_privkey` VARCHAR,
 `they_used_new_channel_key` INTEGER,
 `their_verfkey` VARCHAR -- from their invitation message
);

CREATE TABLE `inbound_messages`
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `cid` INTEGER, -- points to addressbook entry
 `seqnum` INTEGER, -- scoped to channel
 `payload_json` VARCHAR
);
