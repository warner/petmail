CREATE TABLE `version`
(
 `version` INTEGER -- contains one row, set to 1
);

CREATE TABLE `node` -- contains one row
(
 `webport` STRING
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

CREATE TABLE `mailboxes` -- one per mailbox
(
 `descriptor` STRING, -- given to peers, tells them how to send us messages
 `private_descriptor` STRING -- kept secret, tells us how to read inbox
 `TID` STRING -- Transport ID, shared with mailbox, identifies our queue
);

CREATE TABLE `client_profile` -- contains one row
(
 `name` STRING,
 `icon_data` STRING
);

CREATE TABLE `invitations` -- data on all pending invitations
(
 `petname` STRING,

 -- these are only used during the invitation process, then discarded
 `code_hex` STRING,
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
 `theirVerfkey` STRING, -- Ed25519 verfkey (long-term), after M2

 -- my (public) record: .channel_pubkey, .CID, .STID, .mailbox_descriptor
 `myTransportRecord` STRING,
 -- my private record: .my_signkey, .my_CID, .my_{old,new}_channel_privkey
 `myPrivateTransportRecord` STRING
);

CREATE TABLE `channel_data` -- contains one row
(
 `CID_privkey` STRING
);

CREATE TABLE `addressbook`
(
 -- our private notes and decisions about them
 `petname` STRING,
 `acked` INTEGER,
 -- public notes about them

 -- things used to send outbound messages
    -- these three are shared among all of the recipient's mailboxes
 `my_signkey` STRING,
 `their_channel_pubkey` STRING, -- from their transport record
 `their_CID` STRING, -- from their transport record
    -- these two will get a separate copy for each mailbox
 `their_STID` STRING, -- from their transport record
 `their_mailbox_descriptor` STRING, -- from their transport record

 -- things used to handle inbound messages
 `my_private_CID` STRING,
 `my_old_channel_privkey` STRING,
 `my_new_channel_privkey` STRING,
 `they_used_new_channel_key` INTEGER,
 `their_verfkey` STRING -- from their invitation message
);
