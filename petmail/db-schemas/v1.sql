
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
 `cid` INTEGER, -- addressbook.id
 `mailbox_record_json` VARCHAR
);
CREATE UNIQUE INDEX `mailbox_cid` ON `mailboxes` (`cid`);

CREATE TABLE `agent_profile` -- contains one row
(
 `advertise_local_mailbox` INTEGER,
 `name` VARCHAR,
 `icon_data` VARCHAR
);

-- data on all pending invitations. This row is created when the invitation
-- code is generated or submitted, and removed when the invitation is
-- complete (we have received their transport record, and they have
-- acknowledged receipt of our own transport record). The addressbook
-- table will have a row pointing here until the invitation is complete.

CREATE TABLE `invitations`
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `channel_id` INTEGER, -- to correlate with an addressbook entry

 `code` VARCHAR,
 `wormhole` VARCHAR, -- serialized magic-wormhole state

 -- they'll get this payload in M2
 --  .channel_pubkey, .CID_key,
 --  .transports[]: .STT, .transport_pubkey, .type, .url
 `payload_for_them` VARCHAR
);

CREATE TABLE `addressbook`
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT, -- the channelID

 -- current+historical data about the invitation process
 --  1: iid,iid.wormhole=NULL,icode=NULL : waiting to allocate code
 --  2: iid,iid.wormhole,icode : waiting for invitation to complete
 --  3: iid=NULL,icode : invitation complete
 `invitation_id` INTEGER, -- points to `invitations` table
 `when_invited` INTEGER, -- memories of how we met them
 `when_accepted` INTEGER,
 `invitation_code` VARCHAR, -- or NULL
 --`acked` INTEGER, -- don't send messages until this is true

 -- our private notes and decisions about them
 `petname` VARCHAR,
 `accept_mailbox_offer` INTEGER, -- boolean

 -- services they've offered to us
 `latest_offered_mailbox_json` VARCHAR,

 -- things used to send outbound messages
    -- these three are shared among all of the recipient's mailboxes
 `next_outbound_seqnum` INTEGER,
 `my_signkey` VARCHAR, -- Ed25519 privkey (long-term), for this peer
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
 `when_received` INTEGER,
 `payload_json` VARCHAR
);

CREATE TABLE `outbound_messages`
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `cid` INTEGER, -- points to addressbook entry
 `when_sent` INTEGER,
 `payload_json` VARCHAR
);
