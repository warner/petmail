
console.log("control.js loaded");

var token; // actually interpolated into the enclosing control.html
var $, d3; // populated in control.html
var messages = {}; // indexed by cid
var addressbook = {}; // indexed by cid
var invitations = {}; // indexed by invite-id
var current_cid = null;

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

function show_contact_details(e) {
  console.log("details", e.id, e);
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

function open_contact_room(e) {
  if (!e.acked)
    return;
  current_cid = e.id;
  console.log("open_contact_room", current_cid);
  d3.select("#send-message-to").text(addressbook[current_cid].petname
                                     + " [" + current_cid + "]");
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
}

function handle_invite_go(e) {
  var petname = $("#invite-petname").val();
  var code = $("#invite-code").val();
  console.log("inviting", petname, code);
  var req = {"token": token, "args": {"petname": petname, "code": code}};
  d3.json("/api/v1/invite").post(JSON.stringify(req),
                                 function(err, r) {
                                   console.log("invited", r.ok);
                                 });
  $("#invite-petname").val("");
  $("#invite-code").val("");
  $("#invite").hide("clip");
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

function main() {
  console.log("onload");

  $("ul.nav a").click(function (e) {
    e.preventDefault();
    $(this).tab("show");
  });

  var ev;
  ev = new EventSource("/api/v1/views/addressbook?token="+token);
  ev.onmessage = update_addressbook;
  ev = new EventSource("/api/v1/views/messages?token="+token);
  ev.onmessage = update_messages;

  $("#invite").hide();
  $("#add-contact").click(function(e) {
    $("#invite").toggle("clip");
  });
  $("div.contact-details-pane").hide();
  $("#invite-code").on("keyup", function(e) {
    if (e.keyCode == 13) // $.ui.keyCode.ENTER
      $("#invite-go").click();
  });

  $("#invite-go").on("click", handle_invite_go);
  $("#send-message-go").on("click", handle_send_message_go);

  console.log("setup done");
}


document.addEventListener("DOMContentLoaded", main);
