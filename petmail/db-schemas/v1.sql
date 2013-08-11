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
);

CREATE TABLE `client_profile` -- contains one row
(
 `name` STRING,
 `icon_data` STRING
);

CREATE TABLE `invitations` -- data on all pending invitations
(
 `code_hex` STRING,
 `petname` STRING,
 `stretchedKey` STRING, -- Ed25519 signing key
 `channelID` STRING, -- Ed25519 verifying key
 `myTempPrivkey` STRING, -- Curve25519 privkey (ephemeral)
 `mySigningKey` STRING, -- Ed25519 privkey, long-term, for this peer
 `theirTempPubkey` STRING, -- Curve25519 pubkey (ephemeral)
 `theirVerfkey` STRING, -- Ed25519 verfkey (long-term), after M2
 `myTransportRecord` STRING,
 `myPrivateTransportRecord` STRING,
 `myMessages` STRING, -- r0:hex,r0-hex of all my sent messages
 `theirMessages` STRING, -- r0:hex,r0-hex of all processed inbound messages
 `nextExpectedMessage` INTEGER
);


CREATE TABLE `addressbook`
(
 `their_verfkey` STRING,
 `their_transport_record_json` STRING,
 `petname` STRING,
 `my_private_transport_record_json` STRING,
 `my_signkey` STRING,
 `acked` INTEGER
);
