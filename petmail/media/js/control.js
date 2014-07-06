
console.log("control.js loaded");

var token; // actually interpolated into the enclosing control.html
var esid;
var $, d3; // populated in control.html
var inbound_messages = {}; // indexed by cid
var outbound_messages = {}; // indexed by cid
var addressbook = {}; // indexed by cid
var invitations = {}; // indexed by invite-id
var current_cid = null;
var contact_details_cid; // the currently-displayed contact
var new_invite_reqid; // the recently-submitted invitation request
var editing_petname = false; // whether the "edit petname" box is open
var mailboxes = {}; // indexed by mid
var advertise_local_mailbox = false;
var local_mailbox_url;

function invite_code_generate(e) {
  d3.json("/api/v1/generate-invitation-code")
    .post(JSON.stringify({"token": token}),
          function(err, r) {
            if (err)
              console.log("generate-invitation-code", err);
            else {
              $("#ask-accept-mailbox input").val("off");
              $("#ask-accept-mailbox").hide();
              $("#invite-code").val(r["code"]).select();
              $("#invite-qrcode")
                .empty()
                .qrcode({text: "petmail:"+r["code"]})
                .show();
            }
          });
}


function handle_invite_go(e) {
  var code = $("#invite-code").val();
  var petname = "New Petname";
  console.log("inviting", petname, code);
  // the reqid merely needs to be unique among the invitation requests
  // submitted by this and other frontends. An accidental collision would
  // cause a minor UI nuisance (the Contact Details panel will be opened
  // spontaneously, and the Petname field prepared for editing, even though
  // the user had not just hit the "Invite" button in that particular
  // frontend)
  var reqid = Math.round(Math.random() * 100000);
  new_invite_reqid = reqid;
  var accept_mailbox = $("#ask-accept-mailbox input").prop("checked");
  var req = {token: token, args: {petname: petname, code: code,
                                  accept_mailbox: accept_mailbox,
                                  reqid: reqid }};
  d3.json("/api/v1/invite").post(JSON.stringify(req),
                                 function(err, r) {
                                   console.log("invited", r.ok);
                                 });
  $("#invite-code").val("");
  $("#invite-qrcode").hide();
  $("#invite").hide("clip");
}

function update_addressbook(data) {
  // "value" is a subset of an "addressbook" row
  if (data.action == "insert" || data.action == "update")
    addressbook[data.id] = data.new_value;
  else if (data.action == "delete")
    delete addressbook[data.id];

  var entries = [];
  var id;
  for (id in addressbook) // id, petname, acked
    entries.push(addressbook[id]);

  function sorter(a,b) {
    if (a.petname.toLowerCase() > b.petname.toLowerCase())
      return 1;
    if (a.petname.toLowerCase() < b.petname.toLowerCase())
      return -1;
    return 0;
  }
  entries.sort(sorter);

  function petname_of(e) {
    if (!e.acked) {
      return e.petname + " (pending)";
    } else {
      return e.petname;
    }
  }

  var s = d3.select("#address-book").selectAll("div.entry")
        .data(entries, function(e) { return e.id; })
        .text(petname_of)
        .attr("class", function(e) { return "entry contact cid-"+e.id; })
        .on("click", show_contact_details)
        .on("dblclick", open_contact_room)
  ;

  s.enter().insert("div")
    .text(petname_of)
    .attr("class", function(e) { return "entry contact cid-"+e.id; })
    .on("click", show_contact_details)
    .on("dblclick", open_contact_room)
  ;
  s.exit().remove();
  s.order();

  if (contact_details_cid !== undefined) {
    show_contact_details(addressbook[contact_details_cid]);
  }

  if (new_invite_reqid !== undefined &&
      data.tags && data.tags.reqid === new_invite_reqid) {
    delete new_invite_reqid;
    show_contact_details(addressbook[data.id]);
    edit_petname_cancel();
    edit_petname_start();
  }
}

function show_contact_details(e) {
  console.log("details", e.id, e);
  var was_open = (contact_details_cid === e.id);
  var was_editing_petname = editing_petname;
  contact_details_cid = e.id;
  edit_petname_cancel();
  $("div.contact-details-pane").show();
  $("#address-book div.entry").removeClass("selected");
  $("#address-book div.cid-"+e.id).addClass("selected");
  $("#contact-details-petname").text(e.petname);
  $("#contact-details-id").text(e.id);

  $("#contact-details-id-type").text("Contact-ID");
  if (e.acked) {
    $("#contact-details-state").hide();
  } else {
    $("#contact-details-state").text("State: waiting for ack");
    $("#contact-details-state").show();
  }
  $("#contact-details-code code").text(e.invitation_code);
  if (was_open && was_editing_petname)
    edit_petname_start();
}

function edit_petname_start() {
  if (editing_petname)
    return;
  editing_petname = true;
  var old_petname = $("#contact-details-petname").text();
  $("#contact-details-petname").hide();
  $("#contact-details-petname-editor").show({
    complete: function() { this.focus(); }
  });
  $("#contact-details-petname-editor").val(old_petname);
}

function edit_petname_cancel() {
  if (!editing_petname)
    return;
  editing_petname = false;
  $("#contact-details-petname").show();
  $("#contact-details-petname-editor").hide();
}

function edit_petname_done() {
  if (!editing_petname)
    return;
  editing_petname = false;
  var old_petname = $("#contact-details-petname").text();
  var new_petname = $("#contact-details-petname-editor").val();
  if (old_petname !== new_petname) {
    $("#contact-details-petname").text("<updating..>");
    var req = {"token": token,
               "args": {"petname": new_petname,
                        "cid": $("#contact-details-id").text()
                       }};
    d3.json("/api/v1/set-petname").post(JSON.stringify(req),
                                        function(err, r) {
                                          console.log("set petname", r.ok);
                                        });
  }
  $("#contact-details-petname").show();
  $("#contact-details-petname-editor").hide();
}

function handle_toggle_edit_petname(e) {
  if (!editing_petname) {
    edit_petname_start();
  } else {
    edit_petname_done();
  }
}

function open_contact_room(e) {
  if (!e.acked)
    return;
  current_cid = e.id;
  console.log("open_contact_room", current_cid);
  d3.select("#send-message-to").text(addressbook[current_cid].petname
                                     + " [" + current_cid + "]");
  $("#tab-rooms").click();
}

function update_inbound_messages(data) {
  if (data.action == "insert" || data.action == "update")
    inbound_messages[data.id] = data.new_value;
  else if (data.action == "delete")
    delete inbound_messages[data.id];

  // "value" is a row of the "inbound_messages" table
  var value = data.new_value; // .id, .cid, .payload_json, .petname
  var payload = JSON.parse(value.payload_json); // .basic
  console.log("basic inbound message", payload.basic);

  update_messages();
}

function update_outbound_messages(data) {
  if (data.action == "insert" || data.action == "update")
    outbound_messages[data.id] = data.new_value;
  else if (data.action == "delete")
    delete outbound_messages[data.id];

  // "value" is a row of the "outbound_messages" table
  var value = data.new_value; // .id, .cid, .payload_json, .petname
  var payload = JSON.parse(value.payload_json); // .basic
  console.log("basic outbound message", payload.basic);

  update_messages();
}

function update_messages() {
  var entries = [];
  for (var id in inbound_messages) {
    var m = inbound_messages[id];
    entries.push({type: "inbound", when: m.when_received, msg: m});
  }
  for (var id in outbound_messages) {
    var m = outbound_messages[id];
    entries.push({type: "outbound", when: m.when_sent, msg: m});
  }

  function sorter(a,b) {
    if (a.when > b.when)
      return 1;
    if (a.when < b.when)
      return -1;
    return 0;
  }
  entries.sort(sorter);

  function render_message(e) {
    var payload = JSON.parse(e.msg.payload_json); // .basic
    var d = new Date(e.when*1000);
    var ds = d.toLocaleTimeString() + ", " + d.toLocaleDateString();
    var who;
    if (e.type === "inbound")
      who = "sent to "+e.msg.petname+"["+e.msg.cid+"]";
    else
      who = "received from "+e.msg.petname+"["+e.msg.cid+"]";
    return payload.basic + "    -- "+ who +" ("+ds+")";
  }
  var s = d3.select("#messages").selectAll("li")
        .data(entries)
        .text(render_message);
  s.enter().append("li")
    .text(render_message);
  s.exit().remove();
}

function handle_send_message_go(e) {
  var msg = $("#send-message-body").val();
  console.log("sending", msg, "to", current_cid);
  var req = {"token": token, "args": {"cid": current_cid, "message": msg}};
  d3.json("/api/v1/send-basic").post(JSON.stringify(req),
                                     function(err, r) {
                                       console.log("sent", r.ok);
                                     });
  $("#send-message-body").val("");
}

function update_mailboxes(data) {
  if (data.action == "insert" || data.action == "update")
    mailboxes[data.id] = data.new_value;
  else if (data.action == "delete")
    delete mailboxes[data.id];
  update_mailbox_warning();
}

function update_local_mailbox(data) {
  advertise_local_mailbox = data.adv_local;
  local_mailbox_url = data.local_url;
  update_mailbox_warning();
}

function update_mailbox_warning() {
  console.log("update_mailbox_warning", mailboxes, advertise_local_mailbox);
  var mw = $("#mailbox-warning");
  if (Object.keys(mailboxes).length) {
    mw.hide("clip");
  } else {
    mw.show();
    if (advertise_local_mailbox) {
      $("#mailbox-warning-yes-local").show();
      $("#mailbox-warning-no-local").hide();
      $("#mailbox-warning-local-listener").text(local_mailbox_url);
    } else {
      $("#mailbox-warning-yes-local").hide();
      $("#mailbox-warning-no-local").show();
    }
  }
}


function handle_backend_event(e) {
 // everything we send is e.type="message" and e.data=JSON
  var data = JSON.parse(e.data);
  console.log("backend_event", data);
  if (data.type == "ready") {
    // EventSource is connected, so start listening
    console.log("subscribing for addressbook+messages");
    eventchannel_subscribe(token, esid, "addressbook", true);
    eventchannel_subscribe(token, esid, "messages", true);
    eventchannel_subscribe(token, esid, "mailboxes", true);
  } else if (data.type == "addressbook") {
    update_addressbook(data);
  } else if (data.type == "inbound-messages") {
    update_inbound_messages(data);
  } else if (data.type == "outbound-messages") {
    update_outbound_messages(data);
  } else if (data.type == "mailboxes") {
    update_mailboxes(data);
  } else if (data.type == "advertise_local_mailbox") {
    update_local_mailbox(data);
  } else {
    console.log("unknown backend event type", data.type);
  }
}

function eventchannel_subscribe(token, esid, topic, catchup) {
  d3.json("/api/v1/eventchannel-subscribe")
    .post(JSON.stringify({"token": token,
                          "args": {
                            "esid": esid,
                            "topic": topic,
                            "catchup": catchup}
                         }),
          function(err, r) {
            if (err)
              console.log("subscribe-"+topic+" err");
          });
}

function main() {
  console.log("onload");

  $("ul.nav a").click(function (e) {
    e.preventDefault();
    $(this).tab("show");
  });
  $("#mailbox-warning").hide();

  $("#invite").hide();
  $("#invite-qrcode").hide();
  $("#invite-code").val("");
  $("#add-contact").click(function(e) {
    $("#invite").toggle("clip");
    $("#invite-code").focus();
  });
  $("#invite-code").on("keyup", function(e) {
    if (e.keyCode == 13) // $.ui.keyCode.ENTER
      $("#invite-go").click();
  });
  $("#ask-accept-mailbox").hide();
  $("#invite-code").on("input", function(e) {
    var code = $(this).val();
    if (code.indexOf("mailbox") === 0)
      $("#ask-accept-mailbox").show();
    else
      $("#ask-accept-mailbox").hide();
  });
  $("#invite-go").on("click", handle_invite_go);
  $("#invite-code-generate").on("click", invite_code_generate);

  $("div.contact-details-pane").hide();
  $("#contact-details-petname-editor").hide();
  $("#contact-details-petname-editor").focus(function() { this.select(); });
  $("#edit-petname").click(handle_toggle_edit_petname);
  $("#contact-details-petname-editor").on("keyup", function(e) {
    if (e.keyCode == 13) // $.ui.keyCode.ENTER
      edit_petname_done();
  });

  $("#send-message-go").on("click", handle_send_message_go);

  d3.json("/api/v1/eventchannel-create")
    .post(JSON.stringify({"token": token}),
          function(err, r) {
            if (err) {
              console.log("create-eventchannel failed", err);
            } else {
              console.log("create-eventchannel done", r.esid);
              esid = r.esid;
              var ev = new EventSource("/api/v1/events/"+esid);
              ev.addEventListener("message", handle_backend_event);
              // when the EventSource's "ready" message is delivered, we'll
              // subscribe for addressbook and messages
            }
          });

  console.log("setup done");
}


document.addEventListener("DOMContentLoaded", main);
