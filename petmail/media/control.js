
console.log("control.js loaded");

function main() {
  console.log("onload");
  var ev = new EventSource("/api/v1/views/messages?token="+token);
  ev.onmessage = function(e) {
    var data = JSON.parse(e.data); // .action, .id, .new_value
    // "value" is a row of the "messages" table
    var value = data.new_value; // .id, .cid, .payload_json
    var payload = JSON.parse(value.payload_json); // .basic
    console.log("basic message", payload.basic);
  };

  var addressbook = {}; // indexed by cid
  ev = new EventSource("/api/v1/views/addressbook?token="+token);
  ev.onmessage = function(e) {
    var data = JSON.parse(e.data); // .action, .id, .new_value
    // "value" is a subset of an "addressbook" row
    if (data.action == "insert" || data.action == "update")
      addressbook[data.id] = data.new_value;
    else if (data.action == "delete")
      delete addressbook[data.id];
    var entries = [];
    for (var id in addressbook)
      entries.push(addressbook[id]);
    var s = d3.select("#address-book").selectAll("li")
      .data(entries, function(e) { return e.id; })
      .text(function(e) {return e.petname;});
    s.enter().append("li")
      .text(function(e) {return e.petname;});
    s.exit().remove();
  };

}


document.addEventListener("DOMContentLoaded", main);
