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

CREATE TABLE `client_config` -- contains one row
(
 `privkey` STRING,
 `pubkey` STRING,
 `inbox_location` STRING
);

CREATE TABLE `client_profile` -- contains one row
(
 `name` STRING,
 `icon_data` STRING
);

CREATE TABLE `invitations` -- data on all pending invitations
(
 `code` STRING,
 `petname` STRING,
 `stretchedKey` STRING, -- Ed25519 signing key
 `channelID` STRING, -- Ed25519 verifying key
 `myTempPrivkey` STRING, -- Curve25519 privkey (ephemeral)
 `mySigningKey` STRING, -- Ed25519 privkey, long-term, for this peer
 `theirTempPubkey` STRING, -- Curve25519 pubkey (ephemeral)
 `myTransportRecord` STRING,
 `myPrivateTransportRecord` STRING,
 `myM1` STRING,
 `myM2` STRING,
 `myM3` STRING,
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
