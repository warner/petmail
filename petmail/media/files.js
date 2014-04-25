
function update_scan_progress(data) {
  //console.log("backup-progress", JSON.stringify(data));
  var boxg = d3.select("#backup-progress svg g.box-group");
  var lineg = d3.select("#backup-progress svg g.line-group");
  var pathg = d3.select("#backup-progress svg g.path-group");
  var dirpath;
  if (data["msgtype"] == "processing file") {
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

  d3.select("#backup-show").on("click", function() {
    var req = {"token": token, "args": {}};
    d3.json("/api/v1/get-whole-backup-tree").post(
      JSON.stringify(req),
      function(err, r) {
        console.log("get-whole-backup-tree returned "+r.data.length+" rows");
        //console.log(JSON.stringify(r.data));
        var rootnode = r.data.root;
        var nodes = r.data.nodes;
        nodes = nodes.filter(function(n) { return n.depth < 5; });
        console.log(nodes.length, "nodes");
        console.log(nodes[0]);
        var nodes_by_parent = d3.nest().key(function(d) {
          return d.parentid;
        }).map(nodes);
        //console.log(nodes_by_parent);
        // adapted from http://bl.ocks.org/mbostock/4063423
        var p = d3.layout.partition()
              .children(function (d) {
                return nodes_by_parent[d.id];
              })
              .value(function (d) {
                return d.cumulative_items;
              })
              //.sort(SOMETHING) // by d.name
              //.size([rootnode.cumulative_items, 5])
        ;
        var layout = p.nodes(rootnode);
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
      });
  });


  console.log("setup done");
}


document.addEventListener("DOMContentLoaded", main);
