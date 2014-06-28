
console.log("control.js loaded");

var token; // actually interpolated into the enclosing control.html
var $, d3; // populated in control.html
var messages = {}; // indexed by cid
var addressbook = {}; // indexed by cid
var invitations = {}; // indexed by invite-id
var current_cid = null;
var contact_details_cid; // the currently-displayed contact
var new_invite_reqid; // the recently-submitted invitation request
var editing_petname = false; // whether the "edit petname" box is open

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
  var req = {"token": token, "args": {"petname": petname, "code": code,
                                      "reqid": reqid }};
  d3.json("/api/v1/invite").post(JSON.stringify(req),
                                 function(err, r) {
                                   console.log("invited", r.ok);
                                 });
  $("#invite-petname").val("");
  $("#invite-code").val("");
  $("#invite").hide("clip");
}

function update_addressbook(e) {
  var data = JSON.parse(e.data); // .action, .id, .new_value

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

  var s = d3.select("#address-book").selectAll("div.entry")
        .data(entries, function(e) { return e.id; })
        .text(function(e) {return e.petname;})
        .attr("class", function(e) { return "entry contact cid-"+e.id; })
        .on("click", show_contact_details)
        .on("dblclick", open_contact_room)
  ;

  s.enter().insert("div")
    .text(function(e) {return e.petname;})
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
  var editing = ($("#contact-details-petname-editor").css("display") == "none");
  if (editing) {
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
}

function update_messages(e) {
  var data = JSON.parse(e.data); // .action, .id, .new_value

  if (data.action == "insert" || data.action == "update")
    messages[data.id] = data.new_value;
  else if (data.action == "delete")
    delete messages[data.id];

  // "value" is a row of the "messages" table
  var value = data.new_value; // .id, .cid, .payload_json, .petname
  var payload = JSON.parse(value.payload_json); // .basic
  console.log("basic message", payload.basic);

  var entries = [];
  for (var id in messages)
    entries.push(messages[id]);
  function render_message(e) {
    var payload = JSON.parse(e.payload_json); // .basic
    return e.petname+"["+e.cid+"]: "+payload.basic;
  }
  var s = d3.select("#messages").selectAll("li")
        .data(entries, function(e) {return e.id;})
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

function handle_backend_event(e) {
  console.log("backend event", e);
  if (e.type == "addressbook")
    update_addressbook(e);
  else if (e.type == "messages")
    update_messages(e);
  else {
    console.log("unknown backend event type", e.type);
  }
}

function main() {
  console.log("onload");

  $("ul.nav a").click(function (e) {
    e.preventDefault();
    $(this).tab("show");
  });

  var ev;
  ev = new EventSource("/api/v1/views/addressbook?token="+token);
  ev.addEventListener("addressbook", handle_backend_event);
  ev = new EventSource("/api/v1/views/messages?token="+token);
  ev.addEventListener("messages", handle_backend_event);

  $("#invite").hide();
  $("#add-contact").click(function(e) {
    $("#invite").toggle("clip");
  });
  $("#invite-code").on("keyup", function(e) {
    if (e.keyCode == 13) // $.ui.keyCode.ENTER
      $("#invite-go").click();
  });
  $("#invite-go").on("click", handle_invite_go);

  $("div.contact-details-pane").hide();
  $("#contact-details-petname-editor").hide();
  $("#contact-details-petname-editor").focus(function() { this.select(); });
  $("#edit-petname").click(handle_toggle_edit_petname);
  $("#contact-details-petname-editor").on("keyup", function(e) {
    if (e.keyCode == 13) // $.ui.keyCode.ENTER
      edit_petname_done();
  });

  $("#send-message-go").on("click", handle_send_message_go);

  console.log("setup done");
}


document.addEventListener("DOMContentLoaded", main);
