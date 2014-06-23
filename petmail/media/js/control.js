
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
  console.log("details", e.type, e.data.id);
  $("div.contact-details-pane").show();
  $("#address-book div.entry").removeClass("selected");
  $("#address-book div."+e.rowid).addClass("selected");
  $("#contact-details-petname").text(e.data.petname);
  $("#contact-details-id").text(e.data.id);
  if (e.type === "invitation") {
    $("#contact-details-id-type").text("Invitation-ID");
    $("#contact-details-state").text("pending invitation ("+
                                     e.data.rx_msgs+")");
  } else {
    $("#contact-details-id-type").text("Contact-ID");
    if (e.data.acked) {
      $("#contact-details-state").hide();
    } else {
      $("#contact-details-state").text("State: waiting for ack");
      $("#contact-details-state").show();
    }
  }
}

function open_contact_room(e) {
  if (e.type !== "contact")
    return;
  current_cid = e.data.id;
  console.log("open_contact_room", current_cid);
  d3.select("#send-message-to").text(addressbook[current_cid].petname
                                     + " [" + current_cid + "]");
}

function update_invitations(e) {
  var data = JSON.parse(e.data); // .action, .id, .new_value

  // "value" is a subset of an "invitations" row
  if (data.action == "insert" || data.action == "update")
    invitations[data.id] = data.new_value;
  else if (data.action == "delete")
    delete invitations[data.id];

  update_combined_addressbook();
}

function update_addressbook(e) {
  var data = JSON.parse(e.data); // .action, .id, .new_value

  // "value" is a subset of an "addressbook" row
  if (data.action == "insert" || data.action == "update")
    addressbook[data.id] = data.new_value;
  else if (data.action == "delete")
    delete addressbook[data.id];

  update_combined_addressbook();
}

function update_combined_addressbook() {
  var entries = [];
  var id;
  for (id in addressbook) // id, petname, acked
    entries.push({type: "contact", data: addressbook[id], rowid: "cid-"+id});
  for (id in invitations) // id, petname, code, when_invited, rx_msgs
    entries.push({type: "invitation", data: invitations[id], rowid: "iid-"+id});

  function sorter(a,b) {
    if (a.data.petname.toLowerCase() > b.data.petname.toLowerCase())
      return 1;
    if (a.data.petname.toLowerCase() < b.data.petname.toLowerCase())
      return -1;
    return 0;
  }
  entries.sort(sorter);

  var s = d3.select("#address-book").selectAll("div.entry")
        .data(entries, function(e) { return e.type + "-" + e.data.id; })
        .text(function(e) {return e.data.petname;})
        .attr("class", function(e) {
          if (e.type == "contact")
            return "entry contact "+e.rowid;
          else
            return "entry invitation "+e.rowid;
        })
        .on("click", show_contact_details)
        .on("dblclick", open_contact_room)
  ;

  s.enter().insert("div")
    .text(function(e) {return e.data.petname;})
    .attr("class", function(e) {
      if (e.type == "contact")
        return "entry contact cid-"+e.data.id;
      else
        return "entry invitation iid-"+e.data.id;
    })
    .on("click", show_contact_details)
    .on("dblclick", open_contact_room)
  ;
  s.exit().remove();
  s.order();
}

function handle_invite_go(e) {
  var petname = d3.select("#invite-petname")[0][0].value;
  var code = d3.select("#invite-code")[0][0].value;
  console.log("inviting", petname, code);
  var req = {"token": token, "args": {"petname": petname, "code": code}};
  d3.json("/api/v1/invite").post(JSON.stringify(req),
                                 function(err, r) {
                                   console.log("invited", r.ok);
                                 });
  d3.select("#invite-petname")[0][0].value = "";
  d3.select("#invite-code")[0][0].value = "";
  $("#invite").hide("clip");
}

function handle_send_message_go(e) {
  var msg = d3.select("#send-message-body")[0][0].value;
  console.log("sending", msg, "to", current_cid);
  var req = {"token": token, "args": {"cid": current_cid, "message": msg}};
  d3.json("/api/v1/send-basic").post(JSON.stringify(req),
                                     function(err, r) {
                                       console.log("sent", r.ok);
                                     });
  d3.select("#send-message-body")[0][0].value = "";
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
  ev = new EventSource("/api/v1/views/invitations?token="+token);
  ev.onmessage = update_invitations;
  ev = new EventSource("/api/v1/views/messages?token="+token);
  ev.onmessage = update_messages;

  $("#invite").hide();
  $("#add-contact").click(function(e) {
    $("#invite").toggle("clip");
  });
  $("div.contact-details-pane").hide();

  d3.select("#invite-go")[0][0].onclick = handle_invite_go;
  d3.select("#send-message-go")[0][0].onclick = handle_send_message_go;

  console.log("setup done");
}


document.addEventListener("DOMContentLoaded", main);
