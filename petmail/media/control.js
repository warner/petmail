
console.log("control.js loaded");

var messages = {}; // indexed by cid
var addressbook = {}; // indexed by cid
var current_cid = null;

function set_current_addressbook(e) {
  current_cid = e.id;
  console.log("current_cid", current_cid);
  d3.select("#send-message-to").text(addressbook[current_cid].petname
                                     + " [" + current_cid + "]");
}

function update_scan_progress(data) {
  //console.log("backup-progress", JSON.stringify(data));
  var boxg = d3.select("#backup-progress svg g.box-group");
  var lineg = d3.select("#backup-progress svg g.line-group");
  var pathg = d3.select("#backup-progress svg g.path-group");
  var dirpath, i;
  if (data["msgtype"] == "processing file") {
    dirpath = data["dirpath"];
    i = data["i"];
  } else if (data["msgtype"] == "scan complete") {
    dirpath = [];
  }
  if (dirpath) {
    var boxes = boxg.selectAll("rect.box")
          .data(dirpath);
    boxes.exit().remove();
    boxes.enter().append("svg:rect").attr("class", "box");
    boxes.attr("width", 100)
      .attr("height", 15)
      .attr("stroke", "black")
      .attr("fill", "#ddf")
      .attr("transform", function(d,i) {
        return "translate(0,"+15*i+")";
      })
    ;
    //console.log(" bp set-rows");
    var lines = lineg.selectAll("rect.line")
          .data(dirpath);
    lines.exit().remove();
    lines.enter().append("svg:rect").attr("class", "line");
    lines.attr("width", 3)
      .attr("height", 10)
      .attr("stroke", "black")
      .attr("fill", "black")
      .attr("transform", function(d,i) {
        var fraction = d.num / d.num_siblings;
        return "translate("+(100 * fraction)+","+(3+15*i)+")";
      })
    ;

    var paths = pathg.selectAll("text.path")
          .data(dirpath);
    paths.exit().remove();
    paths.enter().append("svg:text").attr("class", "path");
    paths.attr("text-anchor", "start")
      .attr("fill", "black")
      .text(function (d) {return d.name;})
      .attr("x", 105)
      .attr("y", function(d,i) {return 15+15*i;})
      /*.attr("transform", function(d,i) {
        var fraction = d.num / d.num_siblings;
        return "translate(105,"+(3+15*i)+")";
      })*/
    ;
  }
  //console.log(" progress done");
};

function main() {
  console.log("onload");

  var ev = new EventSource("/api/v1/views/messages?token="+token);
  ev.onmessage = function(e) {
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
  };

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
      .text(function(e) {return e.petname;})
      .attr("class", function(e) { return "cid-"+e.id; })
      .on("click", set_current_addressbook)
    ;

    s.enter().append("li")
      .text(function(e) {return e.petname;})
      .attr("class", function(e) { return "cid-"+e.id; })
      .on("click", set_current_addressbook)
    ;
    s.exit().remove();
  };

  var st = d3.select("#backup-progress");
  var st2 = st.append("svg:svg");
  var boxg = st2.append("svg:g").attr("class", "box-group");
  var lineg = st2.append("svg:g").attr("class", "line-group");
  var pathg = st2.append("svg:g").attr("class", "path-group");

  ev = new EventSource("/api/v1/views/backup-scan?token="+token);
  ev.onmessage = function(e) {
    update_scan_progress(JSON.parse(e.data));
  };

  d3.select("#invite-go")[0][0].onclick = function(e) {
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
  };

  d3.select("#send-message-go")[0][0].onclick = function(e) {
    var msg = d3.select("#send-message-body")[0][0].value;
    console.log("sending", msg, "to", current_cid);
    var req = {"token": token, "args": {"cid": current_cid, "message": msg}};
    d3.json("/api/v1/send-basic").post(JSON.stringify(req),
                                       function(err, r) {
                                         console.log("sent", r.ok);
                                       });
    d3.select("#send-message-body")[0][0].value = "";
  };

  d3.select("#start-backup")[0][0].onclick = function(e) {
    console.log("start-backup!");
    var req = {"token": token, "args": {}};
    d3.json("/api/v1/start-backup").post(JSON.stringify(req),
                                         function(err, r) {
                                           console.log("start-backup returned:", r);
                                           d3.select("div#backup-status").text(JSON.stringify(r));
                                           });
  };

  console.log("setup done");
}


document.addEventListener("DOMContentLoaded", main);
