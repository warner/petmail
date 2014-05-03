
/* 'scantree_root' is the root of a tree. Each node has a (name, type,
 scanning) properties. "type" is [placeholder, directory, file]. Directory
 nodes have children=[] and eventually (items, size, need_hash_items,
 need_hash_size). File nodes have (size, need_hash=bool).
 */
var scantree_root = {type: "directory", name: ".", children: [], scanning: false};
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
  // note: Array.prototype.findIndex is an ES6 feature that's in FF24, Chrome30,
  // and IE11, but needs a polyfill for older browsers. See
  // http://kangax.github.io/es5-compat-table/es6/ and
  // https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/findIndex

  // returns -1 if the given name is not in the parent's children
  return parent.children.findIndex(function(e) { return e.name === name; });
}

function find_scantree_parent_of(root, localpath_pieces) {
  // We will never be called with just ["."]. The parent node will always
  // exist (and be a directory). The target node might not exist, but we
  // don't look for it. localpath_pieces[0] is always "."
  if (localpath_pieces[0] !== ".") {
    console.log("err: find_scantree_parent_of given", localpath_pieces);
    throw new Error("find_scantree_parent_of given non-dot prefix");
  }
  if (localpath_pieces.length < 2) {
    console.log("err: find_scantree_parent_of too short", localpath_pieces);
    throw new Error("find_scantree_parent_of given short path");
  }
  var here = root;
  localpath_pieces.slice(1, localpath_pieces.length-1).forEach(
    function(name) {
      var i = find_in_children(here, name);
      if (i === -1) {
        console.log("err: find_scantree_parent_of didn't find child", localpath_pieces, name, here.children);
        throw new Error("find_scantree_parent_of didn't find child");
      }
      here = here.children[i];
    });
  return here;
}

function scan_update_enter_dir(root, localpath, childnames) {
  var node;
  if (localpath === ".") {
    node = root;
  } else {
    // the parent node will always exist, and will be a directory
    var localpath_pieces = localpath.split("/");
    var name = localpath_pieces[localpath_pieces.length-1];
    var parentnode = find_scantree_parent_of(root, localpath_pieces);
    var oldindex = find_in_children(parentnode, name);
    var oldnode;
    if (oldindex !== -1) {
      oldnode = parentnode.children[oldindex];
      //console.log("target "+name+" already exists at ["+oldindex+"], type="+oldnode.type);
    }
    if (oldnode && oldnode.type === "directory") {
      //console.log(" oldnode is directory, yay");
      node = oldnode;
    } else {
      if (oldnode) {
        // must remove the old non-directory node
        //console.log(" oldnode is not directory, removing");
        //console.log("  children was: "+JSON.stringify(parentnode.children));
        parentnode.children.splice(oldindex, 1);
        //console.log("  children now: "+JSON.stringify(parentnode.children));
      }
      //console.log(" inserting newnode");
      // now insert the new node
      node = { type: "directory",
               name: name,
               children: [],
               scanning: true
             };
      parentnode.children.push(node);
      //console.log("  children now: "+JSON.stringify(parentnode.children));
    }
  }

  var newchildren = [];
  // re-use children from the old node, add placeholders for the rest
  childnames.forEach(function(newchildname) {
    // TODO: looking up children in oldnode is O(n^2), worst for large dirs.
    // Better O(n) approach is to keep everything sorted and walk both old
    // and new lists in parallel, like an insertion sort.
    var oldchild = find_in_children(node, newchildname);
    //console.log("looking for", newchildname, "found", oldchild);
    if (oldchild === -1) {
      var newnode = { type: "placeholder",
                      name: newchildname,
                      scanning: false
                    };
      newchildren.push(newnode);
    } else {
      newchildren.push(node.children[oldchild]);
    }
  });
  node.children = newchildren;
}

function scan_update_file(root, childpath, size, need_hash) {
  // the parent node will always exist, and will be a directory
  var localpath_pieces = childpath.split("/");
  var name = localpath_pieces[localpath_pieces.length-1];
  var parentnode = find_scantree_parent_of(root, localpath_pieces);
  if (parentnode.type !== "directory") {
    console.log("err: scan_update_file parent isn't dir", localpath_pieces);
    throw new Error("scan_update_file parent isn't dir");
  }
  var oldindex = find_in_children(parentnode, name);
  if (oldindex === -1) {
    console.log("err: scan_update_file didn't find node", localpath_pieces);
    throw new Error("scan_update_file didn't find node");
  }
  parentnode.children[oldindex] = { type: "file",
                                    name: name,
                                    size: size,
                                    need_hash: need_hash };
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
