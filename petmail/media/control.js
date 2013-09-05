
console.log("control.js loaded");

function main() {
    console.log("onload");
    var ev = new EventSource("/api/v1/events/messages?token="+token);
    ev.onmessage = function(e) {
        var data = JSON.parse(e.data); // .action, .id, .new_value
        // "value" is a row of the "messages" table
        var value = data.new_value; // .id, .cid, .payload_json
        var payload = JSON.parse(value.payload_json); // .basic
        console.log("basic message", payload.basic);
    };
}


document.addEventListener("DOMContentLoaded", main);
