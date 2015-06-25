
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

function do_API(api_name, args) {
  var d = $.Deferred();
  d3.json("/api/"+api_name).post(JSON.stringify({token: token, args: args}),
          function(err, r) {
            if (err)
              d.reject(err);
            else
              d.resolve(r);
          });
  return d.promise();
}


function invite_code_generate(e) {
  submit_invite(true, null, "New Petname", false);
}


function handle_accept_go(e) {
  var code = $("#invite-code").val();
  var petname = "New Petname";
  var accept_mailbox = $("#ask-accept-mailbox input").prop("checked");
  if (accept_mailbox)
    petname = "New Mailbox Server";
  console.log("inviting", petname, code);
  submit_invite(false, code, petname, accept_mailbox);
  $("#invite-code").val("");
}

function submit_invite(generate, code, initial_petname, accept_mailbox) {
  // the reqid merely needs to be unique among the invitation requests
  // submitted by this and other frontends. An accidental collision would
  // cause a minor UI nuisance (the Contact Details panel will be opened
  // spontaneously, and the Petname field prepared for editing, even though
  // the user had not just hit the "Invite" button in that particular
  // frontend)
  var reqid = Math.round(Math.random() * 100000);
  new_invite_reqid = reqid;
  var args = { reqid: reqid,
               generate: generate,
               code: code,
               petname: initial_petname,
               accept_mailbox: accept_mailbox };
  do_API("invite", args).then(function(r) { console.log("invited", r.ok);});
}

function update_addressbook(data) {
  // "value" is a subset of an "addressbook" row
  if (data.action == "insert" || data.action == "update")
    addressbook[data.id] = data.new_value;
  else if (data.action == "delete")
    delete addressbook[data.id];

  var entries = [];
  var id;
  for (id in addressbook) {
    // id, petname, acked, invitation_state, invitation_code,
    // accept_mailbox_offer. maybe: mailbox_id, they_offered_mailbox
    entries.push(addressbook[id]);
  }

  function sorter(a,b) {
    if (a.petname.toLowerCase() > b.petname.toLowerCase())
      return 1;
    if (a.petname.toLowerCase() < b.petname.toLowerCase())
      return -1;
    return 0;
  }
  entries.sort(sorter);

  function petname_of(e) {
    if (e.invitation_state != 2) {
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
  if (e.invitation_state == 2) {
    $("#contact-details-state").hide();
    $("#invite-qrcode").hide();
  } else {
    $("#contact-details-state").text("State: waiting, ["+e.invitation_state+"]");
    $("#contact-details-state").show();
    if (e.invitation_state == 1) {
      // emphasize invitation code
      $("#invite-qrcode")
        .empty()
        .qrcode({text: "petmail:"+e.invitation_code})
        .show();
    } else {
      $("#invite-qrcode").hide();
    }
  }
  $("#contact-details-code code").text(e.invitation_code);

  if (e.they_offered_mailbox)
    $("#contact-details-they-offered-mailbox").text("Yes");
  else
    $("#contact-details-they-offered-mailbox").text("No");

  function set_accept_mailbox() {
    $("#accept-mailbox").prop("checked", true);
    $("#contact-details-will-accept-mailbox").show();
    $("#contact-details-will-not-accept-mailbox").hide();
  }
  function clear_accept_mailbox() {
    $("#accept-mailbox").prop("checked", false);
    $("#contact-details-will-accept-mailbox").hide();
    $("#contact-details-will-not-accept-mailbox").show();
  }
  if (e.mailbox_id !== undefined) {
    $("#contact-details-accepted-mailbox").show();
  } else {
    $("#contact-details-accepted-mailbox").hide();
  }
  if (e.accept_mailbox_offer) {
    set_accept_mailbox();
  } else {
    clear_accept_mailbox();
  }

  if (was_open && was_editing_petname)
    edit_petname_start();
}

function accept_mailbox_changestate() {
  do_API("accept-mailbox", { cid: $("#contact-details-id").text(),
                             accept: $("#accept-mailbox").prop("checked") })
    .then(function(r) { console.log("set-accept-mailbox", r.ok); });
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
    var args = { "petname": new_petname,
                 "cid": $("#contact-details-id").text()
               };
    do_API("set-petname", args).then(function(r) {
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
  if (e.invitation_state != 2)
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
      who = "received from "+e.msg.petname+"["+e.msg.cid+"]";
    else
      who = "sent to "+e.msg.petname+"["+e.msg.cid+"]";
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
  var args = {"cid": current_cid, "message": msg};
  do_API("send-basic", args).then(function(r) {
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
  var args = { "esid": esid,
               "topic": topic,
               "catchup": catchup };
  do_API("eventchannel-subscribe", args).fail(function(err) {
    console.log("subscribe-"+topic+" err");
  });
}

function main() {
  console.log("onload");

  // initial state of the UI
  $("#mailbox-warning").hide();
  $("#invite").hide();
  $("#invite-qrcode").hide();
  $("#invite-code").val("");
  $("#add-contact-box").hide();
  $("#accept-box").hide();
  $("#ask-accept-mailbox").hide();
  $("div.contact-details-pane").hide();
  $("#contact-details-petname-editor").hide();

  // top-level navigation tabsbar
  $("ul.nav a").click(function (e) {
    e.preventDefault();
    $(this).tab("show");
  });

  // "Add Contact" button
  $("#add-contact").click(function(e) {
    $("#add-contact-box").toggle("clip");
  });

  // generate/accept buttons
  $("#invite-code-generate").on("click", function() {
    $("#add-contact-box").hide("clip");
    invite_code_generate();
  });
  $("#open-accept-box").click(function(e) {
    $("#add-contact").hide("clip");
    $("#add-contact-box").hide("clip");
    $("#accept-box").show("clip");
    $("#invite-code").focus();
  });

  // accept-code box
  $("#invite-code").on("keyup", function(e) {
    if (e.keyCode == 13) // $.ui.keyCode.ENTER
      $("#invite-go").click();
  });
  $("#invite-code").on("input", function(e) {
    var code = $(this).val();
    if (code.indexOf("mailbox") === 0)
      $("#ask-accept-mailbox").show();
    else
      $("#ask-accept-mailbox").hide();
  });
  $("#invite-go").on("click", function () {
    $("#accept-box").hide("clip");
    $("#add-contact").show("clip");
    handle_accept_go();
  });
  $("#invite-cancel").on("click", function () {
    $("#accept-box").hide("clip");
    $("#add-contact").show("clip");
    //handle_invite_cancel();
  });

  // contact details
  $("#contact-details-petname-editor").focus(function() { this.select(); });
  $("#edit-petname").click(handle_toggle_edit_petname);
  $("#contact-details-petname-editor").on("keyup", function(e) {
    if (e.keyCode == 13) // $.ui.keyCode.ENTER
      edit_petname_done();
  });
  $("#accept-mailbox").on("click", accept_mailbox_changestate);

  // basic message-sending "room" stub
  $("#send-message-go").on("click", handle_send_message_go);

  // finally connect us to the backend event stream
  do_API("eventchannel-create", {}).then(function(r) {
    console.log("create-eventchannel done", r.esid);
    esid = r.esid;
    var ev = new EventSource("/api/events/"+esid);
    ev.addEventListener("message", handle_backend_event);
    // when the EventSource's "ready" message is delivered, we'll
    // subscribe for addressbook and messages
  }).fail(function(err) {
    console.log("create-eventchannel failed", err);
  });

  console.log("setup done");
}


document.addEventListener("DOMContentLoaded", main);
