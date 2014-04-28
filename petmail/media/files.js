
/* 'scantree_root' is the superroot of a tree, always containing exactly one
 child (named ".") which is the real root. Each non-leaf node is {name,
 children:[], scanning:bool}. Each leaf node is either {type:directory, name,
 items, size, need_hash_items, need_hash_size} (for truncated directories),
 or {type:file, name, size, need_hash:bool}.
 */
var scantree_root = {name: "<superroot>", children: [], scanning: false};
var partition; // a d3.layout.partition() for the sunburst

function update_sunburst() {
  var layout = partition.nodes(scantree_root.children[0]);
  // adapted from http://bl.ocks.org/mbostock/4063423
  // x (value), y (depth), name, depth
  // x is scaled [0,1]
  // y is scaled from [0,1], since default .size() had y=1, depth
  //var maxdepth = d3.max(layout, function(n){return n.depth;});
  //console.log("maxdepth", maxdepth);
  //layout =  layout.filter(function(n){return n.depth<5;});
  //console.log(layout);
  var RADIUS = 300;
  var xscale = d3.scale.linear()
        .range([0, 2*Math.PI]);
  var yscale = d3.scale.linear()
        .range([0, RADIUS]);
  var color = d3.scale.category20c();
  var arc = d3.svg.arc()
        .innerRadius(function(n) {return yscale(n.y);})
        .outerRadius(function(n) {return yscale(n.y+n.dy)-RADIUS/100;})
        .startAngle(function(n) {return xscale(n.x);})
        .endAngle(function(n) {return xscale(n.x+0.99*n.dx);})
  ;
  var arcs = d3.select("g.sunburst").selectAll("path.arc").data(layout);
  arcs.exit().remove();
  arcs.enter().append("svg:path").attr("class", "arc");
  arcs
    .attr("display", function(d) { return d.depth ? null : "none";})
    .attr("d", arc)
    .style("stroke", "#fff")
    .style("fill",
           function(d) { return color((d.children ? d : d.parent).name);})
    .style("fill-rule", "evenodd")
    .attr("title", function(d) {return d.name;});
  ;
}

function find_in_children(parent, name) {
  // note: Array.prototype.find is an ES6 feature that's in FF24, Chrome30,
  // and IE11, but needs a polyfill for older browsers. See
  // http://kangax.github.io/es5-compat-table/es6/ and
  // https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/find
  return parent.children.find(function(e) { return e.name === name; });
}

function find_scantree_node(root, localpath_pieces) {
  // the node will always exist
  var here = root;
  // [0] is always "."
  localpath_pieces.forEach(function(name) {
    here = find_in_children(here, name);
  });
  return here;
}

function scan_update_enter_dir(root, localpath, childnames) {
  var localpath_pieces = localpath.split("/");
  if (localpath_pieces[0] !== ".") {
    console.log("Hey, localpath didn't start with ./", localpath);
    return;
  }
  var parentnode = find_scantree_node(root, localpath_pieces.slice(0, -1));
  var name = localpath_pieces[localpath_pieces.length-1];
  var oldnode = find_in_children(parentnode, name); // or undefined
  // TODO: looking up children in oldnode is O(n^2), worst for large dirs
  var placeholders_to_add;
  var newnode = { name: name,
                  scanning: true,
                  children: [] };
  if (oldnode === undefined) {
    parentnode.children.push(newnode);
    placeholders_to_add = childnames;
  } else {
    // re-use children from the old node, add placeholders for the rest
    placeholders_to_add = [];
    childnames.forEach(function(newchildname) {
      var oldchild = find_in_children(oldnode, newchildname);
      console.log("looking for", newchildname, "found", oldchild);
      if (oldchild !== undefined) {
        oldchild.scanning = true;
        newnode.children.push(oldchild);
      } else {
        placeholders_to_add.push(newchildname);
      }
    });
  }

  placeholders_to_add.forEach(function(childname) {
    // make a placeholder for the child, filled in later
    console.log(" placeholder for", childname);
    newnode.children.push({name: childname, scanning: false, children: []});
    console.log(" newnode", newnode);
  });
}

function scan_update_file(root, childpath, size, need_hash) {
}

function scan_update_exit_dir(root, localpath, cumulative_size) {
}

function update_scan_progress(data) {
  //console.log("backup-progress", JSON.stringify(data));
  var boxg = d3.select("#backup-progress svg g.box-group");
  var lineg = d3.select("#backup-progress svg g.line-group");
  var pathg = d3.select("#backup-progress svg g.path-group");
  var dirpath;
  if (false) {
  } else if (data["msgtype"] == "scan-enter-dir") {
    scan_update_enter_dir(scantree_root, data["localpath"], data["childnames"]);
    // then maybe update layout
    return;
  } else if (data["msgtype"] == "scan-file") {
    scan_update_file(scantree_root, data["childpath"],
                     data["size"], data["need_hash"]);
    // then maybe update layout
    return;
  } else if (data["msgtype"] == "scan-exit-dir") {
    scan_update_exit_dir(scantree_root,
                         data["localpath"], data["cumulative_size"]
                         // also: items need_hash_size need_hash_items
                         );
    // then maybe update layout
    return;
  } else if (data["msgtype"] == "processing file") {
    dirpath = data["dirpath"];
  } else if (data["msgtype"] == "scan complete") {
    dirpath = [];
    d3.select("div#backup-status").text("took "+d3.format(".3g")(data.elapsed)+
                                        "s, scanned "+d3.format(".4s")(data.size) +
                                        " bytes, in "+data.items+" items. "+
                                       "Need to hash "+data.need_to_hash+
                                        " files");
  } else if (data["msgtype"] == "hash_files done") {
    d3.select("div#backup-status").text("took "+d3.format(".3g")(data.elapsed)+
                                        "s, need_to_upload "+d3.format("g")(data.need_to_upload) +
                                        " files");
  } else if (data["msgtype"] == "schedule_uploads done") {
    d3.select("div#backup-status").text("took "+d3.format(".3g")(data.elapsed)+
                                        "s, need_to_upload "+d3.format(".4s")(data.bytes_to_upload)+" bytes in "+d3.format("g")(data.files_to_upload) + " files"
                                        + " (in "+d3.format("g")(data.objects)
                                        + " loose objects and "+
                                        d3.format("g")(data.aggregate_objects)
                                        +" aggregate objects)"
                                       );
  } else if (data["msgtype"] == "upload done") {
    d3.select("div#backup-status").text("took "+d3.format(".3g")(data.elapsed)+
                                        "s, to upload "+d3.format(".4s")(data.bytes_uploaded) + " bytes in "+d3.format("g")(data.objects_uploaded) + " objects");
  } else {
    console.log(data);
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

  var st = d3.select("#backup-progress");
  var st2 = st.append("svg:svg");
  var boxg = st2.append("svg:g").attr("class", "box-group");
  var lineg = st2.append("svg:g").attr("class", "line-group");
  var pathg = st2.append("svg:g").attr("class", "path-group");

  ev = new EventSource("/api/v1/views/backup-scan?token="+token);
  ev.onmessage = function(e) {
    update_scan_progress(JSON.parse(e.data));
  };

  d3.select("#backup-scan").on("click", function (e) {
    console.log("backup: start scan");
    var req = {"token": token, "args": {}};
    d3.json("/api/v1/start-backup-scan").post(
      JSON.stringify(req),
      function(err, r) {
        console.log("start-backup-scan returned:", r);
        d3.select("div#backup-status").text(JSON.stringify(r));
      });
  });

  d3.select("#backup-hash").on("click", function() {
    console.log("backup: start hash");
    var req = {"token": token, "args": {}};
    d3.json("/api/v1/start-backup-hash").post(
      JSON.stringify(req),
      function(err, r) {
        console.log("start-backup-hash returned:", r);
        d3.select("div#backup-status").text(JSON.stringify(r));
      });
  });

  d3.select("#backup-schedule").on("click", function() {
    console.log("backup: start schedule");
    var req = {"token": token, "args": {}};
    d3.json("/api/v1/start-backup-schedule").post(
      JSON.stringify(req),
      function(err, r) {
        console.log("start-backup-schedule returned:", r);
        d3.select("div#backup-status").text(JSON.stringify(r));
      });
  });

  d3.select("#backup-upload").on("click", function() {
    console.log("backup: start upload");
    var req = {"token": token, "args": {}};
    d3.json("/api/v1/start-backup-upload").post(
      JSON.stringify(req),
      function(err, r) {
        console.log("start-backup-upload returned:", r);
        d3.select("div#backup-status").text(JSON.stringify(r));
      });
  });

  var bb = d3.select("#backup-bigbox").append("svg:svg").attr("class", "filetree");
  bb.append("svg:g")
    .attr("class", "sunburst")
    .attr("transform", "translate(300, 300)");
  ;
  partition = d3.layout.partition()
    .value(function(d) {
      return d.size;
    });
              //.children(function (d) {
              //  return nodes_by_parent[d.id];
              //})
              //.sort(SOMETHING) // by d.name
              //.size([rootnode.cumulative_items, 5])

  d3.select("#backup-show").on("click", function() {
    var req = {"token": token, "args": {}};
    d3.json("/api/v1/backup-send-latest-snapshot").post(
      JSON.stringify(req),
      function(err, r) {
        console.log("backup-sent-latest-snapshot returned:", r);
      });
  });


  console.log("setup done");
}


document.addEventListener("DOMContentLoaded", main);
